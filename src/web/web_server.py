import json
import logging
from pathlib import Path

from flask import Flask, request as flask_request, jsonify, send_from_directory, make_response
from flask_socketio import SocketIO, join_room, leave_room

from config import Config
from db.database import Database
from domain.analysed_text import AnalysedText
from domain.transcript import Utterance
from domain.types import JobId, JobStatus, AnalysisStatus, FactCheckStatus, AnnotationId
from job.job_builder import JobBuilder
from job.job_runner import JobRunner
from web.socket_emitter import SocketEmitter

log = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"


class WebServer:
    def __init__(self, config: Config, database: Database) -> None:
        self._config = config
        self._database = database
        self._demo = config.get("demo", False)
        self._job_builder: JobBuilder | None = None
        self._job_runner: JobRunner | None = None
        self._app = Flask(__name__, static_folder=str(_WEB_DIR), static_url_path="")
        self._socketio = SocketIO(self._app, cors_allowed_origins="*", async_mode="threading")
        self._emitter = SocketEmitter(self._socketio)
        self._register_routes()
        self._register_socket_events()

    @property
    def socketio(self) -> SocketIO:
        return self._socketio

    @property
    def emitter(self) -> SocketEmitter:
        return self._emitter

    def set_job_builder(self, job_builder: JobBuilder) -> None:
        self._job_builder = job_builder

    def set_job_runner(self, job_runner: JobRunner) -> None:
        self._job_runner = job_runner

    def _demo_guard(self) -> tuple | None:
        if self._demo:
            return jsonify({"error": "Demo mode: this action is disabled"}), 403
        return None

    def _register_routes(self) -> None:
        app = self._app

        @app.route("/")
        def index():
            html = (_WEB_DIR / "index.html").read_text()
            meta = f'<meta name="demo" content="{"true" if self._demo else "false"}">'
            html = html.replace("</head>", f"{meta}\n</head>", 1)
            resp = make_response(html)
            resp.headers["Content-Type"] = "text/html"
            return resp

        @app.route("/api/jobs")
        def list_jobs():
            return jsonify([j.to_dict() for j in self._database.list_jobs()])

        @app.route("/jobs", methods=["POST"])
        def create_job():
            blocked = self._demo_guard()
            if blocked:
                return blocked
            if flask_request.content_type and flask_request.content_type.startswith("multipart/"):
                data = json.loads(flask_request.form["data"])
                audio_file = flask_request.files.get("file")
            else:
                data = flask_request.get_json()
                audio_file = None

            job_id = self._job_builder.build_from_dict(data)

            if audio_file:
                uploads_dir = Path(self._config.get("paths.uploads"))
                uploads_dir.mkdir(parents=True, exist_ok=True)
                dest = uploads_dir / f"{job_id}.mp3"
                audio_file.save(dest)
                log.info("[%s] Saved uploaded MP3 to %s", job_id, dest)
                self._job_builder.set_source_path(job_id, f"{job_id}.mp3")

            job = self._database.get_job(job_id)
            self._emitter.job_created(job, room="lobby")
            return jsonify({"job_id": job_id}), 201

        @app.route("/jobs/<job_id>/start", methods=["POST"])
        def start_job(job_id):
            blocked = self._demo_guard()
            if blocked:
                return blocked
            jid = JobId(job_id)
            job = self._database.get_job(jid)
            if not job:
                return jsonify({"error": "Job not found"}), 404

            self._job_runner.start_job(jid)
            self._emitter.job_status(jid, JobStatus.INGESTING, room="lobby")
            return jsonify({"job_id": job_id}), 200

        @app.route("/jobs/<job_id>/review", methods=["POST"])
        def request_review(job_id):
            blocked = self._demo_guard()
            if blocked:
                return blocked
            jid = JobId(job_id)
            job = self._database.get_job(jid)
            if not job:
                return jsonify({"error": "Job not found"}), 404

            if job.status not in (JobStatus.INGESTING, JobStatus.ANALYSING):
                return jsonify({"error": "Job is not in a reviewable state"}), 400

            # Check that the job has at least some analysed utterances
            analyses = self._database.get_all_analysed_texts(jid)
            if not analyses:
                return jsonify({"error": "No analysed utterances available for review"}), 400

            self._database.start_early_review(jid)
            self._emitter.job_status(jid, JobStatus.REVIEWING, room="lobby")
            return jsonify({"job_id": job_id, "status": "reviewing"}), 202

        @app.route("/jobs/<job_id>/abort", methods=["POST"])
        def abort_job(job_id):
            blocked = self._demo_guard()
            if blocked:
                return blocked
            jid = JobId(job_id)
            job = self._database.get_job(jid)
            if not job:
                return jsonify({"error": "Job not found"}), 404
            if job.status in (JobStatus.COMPLETE, JobStatus.ABORTED):
                return jsonify({"error": "Job is already finished"}), 400

            self._job_runner.abort_job(jid)
            self._emitter.job_status(jid, JobStatus.ABORTED, room="lobby")
            return jsonify({"job_id": job_id, "status": "aborted"}), 200

        @app.route("/jobs/<job_id>/annotations/<annotation_id>/retry-fact-check", methods=["POST"])
        def retry_fact_check(job_id, annotation_id):
            blocked = self._demo_guard()
            if blocked:
                return blocked
            jid = JobId(job_id)
            if not self._database.get_job(jid):
                return jsonify({"error": "Job not found"}), 404

            reset = self._database.reset_annotation_fact_check(AnnotationId(annotation_id))
            if not reset:
                return jsonify({"error": "Annotation not found or has no fact check"}), 404

            self._emitter.fact_check_reset(jid, AnnotationId(annotation_id), room=jid)
            return jsonify({"job_id": job_id, "annotation_id": annotation_id}), 200

        @app.route("/jobs/<job_id>", methods=["DELETE"])
        def delete_job(job_id):
            blocked = self._demo_guard()
            if blocked:
                return blocked
            jid = JobId(job_id)
            deleted = self._database.delete_job(jid)
            if not deleted:
                return jsonify({"error": "Job not found"}), 404
            self._emitter.job_deleted(jid, room="lobby")
            return jsonify({"job_id": job_id}), 200

    def _register_socket_events(self) -> None:
        sio = self._socketio

        @sio.on("connect")
        def handle_connect():
            join_room("lobby")
            log.info("Client connected and joined lobby")

        @sio.on("join_job")
        def handle_join_job(data):
            job_id = JobId(data["job_id"])
            sid = flask_request.sid
            join_room(job_id)
            log.info("Client %s joined job room: %s", sid, job_id)
            self._replay_job_state(job_id, to=sid)

        @sio.on("leave_job")
        def handle_leave_job(data):
            job_id = JobId(data["job_id"])
            leave_room(job_id)
            log.info("Client left job room: %s", job_id)

        @sio.on("audio_chunk")
        def handle_audio_chunk(data):
            if self._demo:
                return
            job_id = JobId(data["job_id"])
            audio_bytes = data["audio"]
            source = self._job_runner.get_streaming_source(job_id)
            if source:
                source.receive_audio(audio_bytes)
            else:
                log.warning("[%s] Received audio chunk but no streaming source found", job_id)

        @sio.on("audio_stop")
        def handle_audio_stop(data):
            if self._demo:
                return
            job_id = JobId(data["job_id"])
            source = self._job_runner.get_streaming_source(job_id)
            if source:
                source.stop_stream()
                log.info("[%s] Audio stream stopped by client", job_id)

    def _replay_job_state(self, job_id: JobId, to: str) -> None:
        job = self._database.get_job(job_id)
        if not job:
            return

        self._emitter.job_status(job_id, job.status, to=to)

        stats = self._database.get_job_stats(job_id)
        if stats:
            self._emitter.job_stats(job_id, stats, to=to)

        utterances = self._database.get_utterances(job_id)
        for utt in utterances:
            self._replay_transcription(job_id, utt, to)
            self._replay_analysis(job_id, utt, to)

        self._replay_review(job_id, job, to)

        self._emitter.replay_complete(job_id, to=to)

    def _replay_transcription(self, job_id: JobId, utt: Utterance, to: str) -> None:
        self._emitter.transcription(job_id, utt, to=to)

    def _replay_analysis(self, job_id: JobId, utt: Utterance, to: str) -> None:
        if utt.analysis_status == AnalysisStatus.FAILED:
            self._emitter.analysis_failed(job_id, utt.id, to=to)
            return

        parts = self._database.get_analysed_parts(utt.id)
        if not parts:
            return

        analysed_text = AnalysedText(
            utterance_id=utt.id,
            text=utt.text,
            analysed_parts=tuple(parts),
            remainder=utt.analysis_remainder,
        )
        self._emitter.analysis(job_id, analysed_text, to=to)

        for part in parts:
            for annotation in part.annotations:
                self._replay_fact_check(job_id, annotation, to)

    def _replay_review(self, job_id: JobId, job, to: str) -> None:
        if job.status == JobStatus.COMPLETE:
            review_data = self._database.get_review(job_id)
            if review_data:
                self._emitter.transcript_review(job_id, review_data, to=to)

    def _replay_fact_check(self, job_id: JobId, annotation, to: str) -> None:
        if annotation.fact_check_status == FactCheckStatus.COMPLETE:
            self._emitter.fact_check(
                job_id, annotation.id,
                annotation.fact_check_verdict, annotation.fact_check_note,
                citations=annotation.fact_check_citations,
                to=to,
            )
        elif annotation.fact_check_status == FactCheckStatus.FAILED:
            self._emitter.fact_check(
                job_id, annotation.id,
                "FAILED", annotation.fact_check_note or "",
                to=to,
            )

    def start(self) -> None:
        port = self._config.get("webserver.port")
        log.info("Starting web server on port %d", port)
        self._socketio.run(self._app, host="0.0.0.0", port=port, debug=False, use_reloader=False,
                           allow_unsafe_werkzeug=True)
