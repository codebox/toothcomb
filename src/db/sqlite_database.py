import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from db.database import Database
from domain.analysed_text import Annotation, AnnotationType, AnalysedPart, AnalysedText
from domain.job import Job
from domain.llm_usage import LLMUsage
from domain.transcript import Utterance
from domain.types import (
    JobId, UtteranceId, AnnotationId, AnalysisResultId, ModelName,
    JobStatus, AnalysisStatus, FactCheckStatus,
)

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL DEFAULT '',
    config          TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'init',
    review_claimed  INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS utterances (
    id                  TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL REFERENCES jobs(id),
    seq                 INTEGER NOT NULL,
    speaker             TEXT NOT NULL DEFAULT '',
    text                TEXT NOT NULL DEFAULT '',
    offset_seconds      REAL NOT NULL DEFAULT 0,
    analysis_status     TEXT NOT NULL DEFAULT 'pending',
    analysis_remainder  TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id              TEXT PRIMARY KEY,
    utterance_id    TEXT NOT NULL REFERENCES utterances(id),
    seq             INTEGER NOT NULL,
    corrected_text  TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS annotations (
    id                  TEXT PRIMARY KEY,
    analysis_result_id  TEXT NOT NULL REFERENCES analysis_results(id),
    type                TEXT NOT NULL,
    notes               TEXT NOT NULL DEFAULT '',
    fact_check_query    TEXT,
    fact_check_status   TEXT,
    fact_check_verdict  TEXT,
    fact_check_note     TEXT,
    fact_check_citations TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transcript_reviews (
    job_id          TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    findings_json   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_stats (
    job_id              TEXT NOT NULL REFERENCES jobs(id),
    model               TEXT NOT NULL,
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    request_count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (job_id, model)
);

CREATE TABLE IF NOT EXISTS rate_limits (
    model           TEXT PRIMARY KEY,
    retry_after     REAL NOT NULL,
    backoff_level   INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_utterances_job_id ON utterances(job_id);
CREATE INDEX IF NOT EXISTS idx_analysis_results_utterance_id ON analysis_results(utterance_id);
CREATE INDEX IF NOT EXISTS idx_annotations_analysis_result_id ON annotations(analysis_result_id);
CREATE INDEX IF NOT EXISTS idx_annotations_fact_check_status ON annotations(fact_check_status);
"""

_BUSY_TIMEOUT_MS = 5000


class SQLiteDatabase(Database):
    """Thread-safe SQLite database using per-thread connections.

    Each thread gets its own connection via thread-local storage.
    SQLite's file-level locking handles write serialisation.
    WAL mode allows concurrent readers alongside a single writer.
    """

    def __init__(self, db_path: str = "db/toothcomb.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._local = threading.local()
        self._init_schema()
        log.info("SQLite database ready at %s", db_path)

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        self._get_conn().executescript(_SCHEMA)

    # -- Row → Domain mapping --

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            id=JobId(row["id"]),
            title=row["title"],
            config=row["config"],
            status=JobStatus(row["status"]),
            started_at=row["started_at"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_utterance(row: sqlite3.Row) -> Utterance:
        return Utterance(
            id=UtteranceId(row["id"]),
            speaker=row["speaker"],
            text=row["text"],
            seq=row["seq"],
            job_id=JobId(row["job_id"]),
            offset_seconds=row["offset_seconds"],
            analysis_status=AnalysisStatus(row["analysis_status"]),
            analysis_remainder=row["analysis_remainder"],
        )

    @staticmethod
    def _row_to_annotation(row: sqlite3.Row, job_id: JobId = JobId("")) -> Annotation:
        fc_status = FactCheckStatus(row["fact_check_status"]) if row["fact_check_status"] else None
        citations_raw = row["fact_check_citations"]
        citations = json.loads(citations_raw) if citations_raw else None
        return Annotation(
            id=AnnotationId(row["id"]),
            type=AnnotationType(row["type"]),
            notes=row["notes"],
            fact_check_query=row["fact_check_query"],
            fact_check_status=fc_status,
            fact_check_verdict=row["fact_check_verdict"],
            fact_check_note=row["fact_check_note"],
            fact_check_citations=citations,
            job_id=job_id,
        )

    # -- Jobs --

    def create_job(self, job: Job) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO jobs (id, title, config) VALUES (?, ?, ?)",
            (job.id, job.title, job.config),
        )
        conn.commit()
        log.info("Job %s saved to database", job.id)

    def update_job_config(self, job_id: JobId, config_json: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE jobs SET config = ?, updated_at = datetime('now') WHERE id = ?",
            (config_json, job_id),
        )
        conn.commit()

    def update_job_status(self, job_id: JobId, status: JobStatus) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE jobs SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status.value, job_id),
        )
        conn.commit()

    def set_job_started_at(self, job_id: JobId) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE jobs SET started_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (job_id,),
        )
        conn.commit()

    def advance_to_analysing(self, job_id: JobId) -> bool:
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE jobs SET status = 'analysing', updated_at = datetime('now') "
            "WHERE id = ? AND status = 'ingesting'",
            (job_id,),
        )
        conn.commit()
        return cursor.rowcount > 0

    def try_advance_to_reviewing(self, job_id: JobId) -> bool:
        conn = self._get_conn()
        row = conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM utterances WHERE job_id = j.id
                    AND analysis_status NOT IN ('complete', 'failed')) AS pending_analysis,
                (SELECT COUNT(*) FROM annotations a
                    JOIN analysis_results ar ON a.analysis_result_id = ar.id
                    JOIN utterances u ON ar.utterance_id = u.id
                    WHERE u.job_id = j.id
                    AND a.fact_check_query IS NOT NULL
                    AND a.fact_check_status NOT IN ('complete', 'failed')) AS pending_fact_checks
            FROM jobs j WHERE j.id = ? AND j.status = 'analysing'
        """, (job_id,)).fetchone()

        if not row:
            return False
        if row["pending_analysis"] > 0:
            return False
        if row["pending_fact_checks"] > 0:
            return False

        cursor = conn.execute(
            "UPDATE jobs SET status = 'reviewing', updated_at = datetime('now') "
            "WHERE id = ? AND status = 'analysing'",
            (job_id,),
        )
        conn.commit()
        return cursor.rowcount > 0

    def start_early_review(self, job_id: JobId) -> bool:
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE jobs SET status = 'reviewing', updated_at = datetime('now') "
            "WHERE id = ? AND status IN ('ingesting', 'analysing')",
            (job_id,),
        )
        conn.commit()
        return cursor.rowcount > 0

    def try_advance_to_complete(self, job_id: JobId) -> bool:
        conn = self._get_conn()
        # Check no pending or processing fact checks remain
        row = conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM annotations a
                    JOIN analysis_results ar ON a.analysis_result_id = ar.id
                    JOIN utterances u ON ar.utterance_id = u.id
                    WHERE u.job_id = j.id
                    AND a.fact_check_status IN ('pending', 'processing')) AS outstanding_fact_checks
            FROM jobs j WHERE j.id = ? AND j.status = 'reviewing'
        """, (job_id,)).fetchone()

        if not row:
            return False
        if row["outstanding_fact_checks"] > 0:
            return False

        cursor = conn.execute(
            "UPDATE jobs SET status = 'complete', updated_at = datetime('now') "
            "WHERE id = ? AND status = 'reviewing'",
            (job_id,),
        )
        conn.commit()
        return cursor.rowcount > 0

    def get_job(self, job_id: JobId) -> Optional[Job]:
        row = self._get_conn().execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self) -> list[Job]:
        rows = self._get_conn().execute(
            "SELECT * FROM jobs ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def delete_job(self, job_id: JobId) -> bool:
        conn = self._get_conn()
        conn.execute("""
            DELETE FROM annotations WHERE analysis_result_id IN (
                SELECT ar.id FROM analysis_results ar
                JOIN utterances u ON ar.utterance_id = u.id
                WHERE u.job_id = ?
            )
        """, (job_id,))
        conn.execute("""
            DELETE FROM analysis_results WHERE utterance_id IN (
                SELECT id FROM utterances WHERE job_id = ?
            )
        """, (job_id,))
        conn.execute("DELETE FROM utterances WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM transcript_reviews WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM job_stats WHERE job_id = ?", (job_id,))
        cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            log.info("Job %s and all associated data deleted", job_id)
        return deleted

    # -- Utterances --

    def create_utterance(self, utterance: Utterance) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO utterances (id, job_id, seq, speaker, text, offset_seconds, analysis_status) VALUES (?, ?, ?, ?, ?, ?, 'buffered')",
            (utterance.id, utterance.job_id, utterance.seq, utterance.speaker,
             utterance.text, utterance.offset_seconds),
        )
        conn.commit()

    def next_utterance_seq(self, job_id: JobId) -> int:
        row = self._get_conn().execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM utterances WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return row["next_seq"]

    def claim_utterance_for_analysis(self, job_id: JobId) -> Optional[Utterance]:
        conn = self._get_conn()

        row = conn.execute("""
            SELECT u.* FROM utterances u
            JOIN jobs j ON u.job_id = j.id
            WHERE u.job_id = ? AND u.analysis_status = 'pending'
            AND j.status IN ('ingesting', 'analysing')
            AND NOT EXISTS (
                SELECT 1 FROM utterances prev
                WHERE prev.job_id = u.job_id AND prev.seq < u.seq
                AND prev.analysis_status NOT IN ('complete', 'failed')
            )
            ORDER BY u.seq LIMIT 1
        """, (job_id,)).fetchone()

        if not row:
            return None

        cursor = conn.execute(
            "UPDATE utterances SET analysis_status = 'processing' WHERE id = ? AND analysis_status = 'pending'",
            (row["id"],),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return self._row_to_utterance(row)

    def complete_utterance_analysis(self, utterance_id: UtteranceId, remainder: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE utterances SET analysis_status = 'complete', analysis_remainder = ? WHERE id = ?",
            (remainder, utterance_id),
        )
        conn.commit()

    def fail_utterance_analysis(self, utterance_id: UtteranceId) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE utterances SET analysis_status = 'failed' WHERE id = ?",
            (utterance_id,),
        )
        conn.commit()

    def get_utterance(self, utterance_id: UtteranceId) -> Optional[Utterance]:
        row = self._get_conn().execute(
            "SELECT * FROM utterances WHERE id = ?", (utterance_id,)
        ).fetchone()
        return self._row_to_utterance(row) if row else None

    def get_utterances(self, job_id: JobId) -> list[Utterance]:
        rows = self._get_conn().execute(
            "SELECT * FROM utterances WHERE job_id = ? ORDER BY seq",
            (job_id,),
        ).fetchall()
        return [self._row_to_utterance(r) for r in rows]

    def get_utterance_context(self, job_id: JobId, seq: int, context_count: int) -> list[Utterance]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM utterances
               WHERE job_id = ? AND seq <= ?
               ORDER BY seq DESC LIMIT ?""",
            (job_id, seq, context_count + 1),
        ).fetchall()
        utterances = []
        for r in reversed(rows):
            utt = self._row_to_utterance(r)
            # Use corrected text from analysis if available
            ar_rows = conn.execute(
                """SELECT corrected_text FROM analysis_results
                   WHERE utterance_id = ? ORDER BY seq""",
                (utt.id,),
            ).fetchall()
            if ar_rows:
                corrected = " ".join(ar["corrected_text"] for ar in ar_rows)
                utt = Utterance(id=utt.id, speaker=utt.speaker, text=corrected,
                                seq=utt.seq, job_id=utt.job_id, offset_seconds=utt.offset_seconds,
                                analysis_status=utt.analysis_status, analysis_remainder=utt.analysis_remainder)
            utterances.append(utt)
        return utterances

    def get_previous_remainder(self, job_id: JobId, seq: int) -> str:
        if seq <= 1:
            return ""
        row = self._get_conn().execute(
            """SELECT analysis_remainder FROM utterances
               WHERE job_id = ? AND seq < ? AND analysis_status = 'complete'
               ORDER BY seq DESC LIMIT 1""",
            (job_id, seq),
        ).fetchone()
        return row["analysis_remainder"] if row else ""

    def get_following_text(self, job_id: JobId, seq: int) -> str:
        rows = self._get_conn().execute(
            """SELECT text FROM utterances
               WHERE job_id = ? AND seq > ?
               ORDER BY seq LIMIT 3""",
            (job_id, seq),
        ).fetchall()
        if not rows:
            return ""
        return " ".join(r["text"] for r in rows)

    # -- Analysis buffer --

    def flush_analysis_buffer(self, job_id: JobId, min_words: int) -> dict | None:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, text FROM utterances WHERE job_id = ? AND analysis_status = 'buffered' ORDER BY seq",
            (job_id,),
        ).fetchall()

        if not rows:
            return None

        total_words = sum(len(r["text"].split()) for r in rows)
        if total_words < min_words:
            return None

        return self._flush_buffered(conn, rows)

    def force_flush_analysis_buffer(self, job_id: JobId) -> dict | None:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, text FROM utterances WHERE job_id = ? AND analysis_status = 'buffered' ORDER BY seq",
            (job_id,),
        ).fetchall()

        if not rows:
            return None

        return self._flush_buffered(conn, rows)

    @staticmethod
    def _flush_buffered(conn, rows) -> dict:
        if len(rows) == 1:
            conn.execute(
                "UPDATE utterances SET analysis_status = 'pending' WHERE id = ?",
                (rows[0]["id"],),
            )
            conn.commit()
            return {"merged_ids": [], "target_id": rows[0]["id"], "combined_text": rows[0]["text"]}

        combined_text = " ".join(r["text"] for r in rows)
        target_id = rows[-1]["id"]
        merged_ids = [r["id"] for r in rows[:-1]]

        conn.execute(
            "DELETE FROM utterances WHERE id IN ({})".format(",".join("?" * len(merged_ids))),
            merged_ids,
        )
        conn.execute(
            "UPDATE utterances SET text = ?, analysis_status = 'pending' WHERE id = ?",
            (combined_text, target_id),
        )
        conn.commit()
        return {"merged_ids": merged_ids, "target_id": target_id, "combined_text": combined_text}

    # -- Analysis Results & Annotations --

    def create_analysis_result(
        self, result_id: AnalysisResultId, utterance_id: UtteranceId, seq: int, corrected_text: str
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO analysis_results (id, utterance_id, seq, corrected_text) VALUES (?, ?, ?, ?)",
            (result_id, utterance_id, seq, corrected_text),
        )
        conn.commit()

    def create_annotation(self, annotation: Annotation, analysis_result_id: AnalysisResultId) -> None:
        if annotation.fact_check_verdict:
            fc_status = "complete"
        elif annotation.fact_check_query:
            fc_status = "pending"
        else:
            fc_status = None
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO annotations
               (id, analysis_result_id, type, notes, fact_check_query,
                fact_check_status, fact_check_verdict, fact_check_note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (annotation.id, analysis_result_id, annotation.type.value,
             annotation.notes, annotation.fact_check_query, fc_status,
             annotation.fact_check_verdict, annotation.fact_check_note),
        )
        conn.commit()

    def get_analysed_parts(self, utterance_id: UtteranceId) -> list[AnalysedPart]:
        conn = self._get_conn()
        result_rows = conn.execute(
            "SELECT * FROM analysis_results WHERE utterance_id = ? ORDER BY seq",
            (utterance_id,),
        ).fetchall()

        parts = []
        for r in result_rows:
            ann_rows = conn.execute(
                "SELECT * FROM annotations WHERE analysis_result_id = ?",
                (r["id"],),
            ).fetchall()
            annotations = tuple(self._row_to_annotation(a) for a in ann_rows)
            parts.append(AnalysedPart(corrected_text=r["corrected_text"], annotations=annotations))
        return parts

    def get_annotations(self, analysis_result_id: AnalysisResultId) -> list[Annotation]:
        rows = self._get_conn().execute(
            "SELECT * FROM annotations WHERE analysis_result_id = ?",
            (analysis_result_id,),
        ).fetchall()
        return [self._row_to_annotation(r) for r in rows]

    # -- Fact Checks --

    def claim_fact_check(self) -> Optional[Annotation]:
        conn = self._get_conn()
        row = conn.execute("""
            SELECT a.*, u.job_id
            FROM annotations a
            JOIN analysis_results ar ON a.analysis_result_id = ar.id
            JOIN utterances u ON ar.utterance_id = u.id
            JOIN jobs j ON u.job_id = j.id
            WHERE a.fact_check_query IS NOT NULL AND a.fact_check_status = 'pending'
            AND j.status IN ('ingesting', 'analysing', 'reviewing')
            LIMIT 1
        """).fetchone()

        if not row:
            return None

        cursor = conn.execute(
            "UPDATE annotations SET fact_check_status = 'processing' WHERE id = ? AND fact_check_status = 'pending'",
            (row["id"],),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return self._row_to_annotation(row, job_id=JobId(row["job_id"]))

    def complete_fact_check(self, annotation_id: AnnotationId, verdict: str, note: str,
                            citations: list[dict] | None = None) -> None:
        conn = self._get_conn()
        citations_json = json.dumps(citations) if citations else None
        conn.execute(
            """UPDATE annotations
               SET fact_check_status = 'complete', fact_check_verdict = ?, fact_check_note = ?,
                   fact_check_citations = ?
               WHERE id = ?""",
            (verdict, note, citations_json, annotation_id),
        )
        conn.commit()

    def fail_fact_check(self, annotation_id: AnnotationId, note: str) -> None:
        conn = self._get_conn()
        conn.execute(
            """UPDATE annotations
               SET fact_check_status = 'failed', fact_check_note = ?
               WHERE id = ?""",
            (note, annotation_id),
        )
        conn.commit()

    def get_annotation(self, annotation_id: AnnotationId) -> Optional[Annotation]:
        row = self._get_conn().execute(
            "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
        ).fetchone()
        return self._row_to_annotation(row) if row else None

    # -- Job Stats --

    def record_llm_usage(self, job_id: JobId, usage: LLMUsage) -> None:
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO job_stats (job_id, model, input_tokens, output_tokens,
                                   cache_read_tokens, cache_creation_tokens, request_count)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(job_id, model) DO UPDATE SET
                input_tokens = input_tokens + excluded.input_tokens,
                output_tokens = output_tokens + excluded.output_tokens,
                cache_read_tokens = cache_read_tokens + excluded.cache_read_tokens,
                cache_creation_tokens = cache_creation_tokens + excluded.cache_creation_tokens,
                request_count = request_count + 1
        """, (job_id, usage.model, usage.input_tokens, usage.output_tokens,
              usage.cache_read_tokens, usage.cache_creation_tokens))
        conn.commit()

    def get_job_stats(self, job_id: JobId) -> list[dict]:
        rows = self._get_conn().execute(
            "SELECT * FROM job_stats WHERE job_id = ?", (job_id,)
        ).fetchall()
        return [
            {
                "model": r["model"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "cache_read_tokens": r["cache_read_tokens"],
                "cache_creation_tokens": r["cache_creation_tokens"],
                "request_count": r["request_count"],
            }
            for r in rows
        ]

    # -- Transcript Review --

    def claim_review(self) -> Optional[Job]:
        conn = self._get_conn()
        # Only claim if status is 'reviewing' and no processing fact checks remain
        row = conn.execute("""
            SELECT j.* FROM jobs j
            WHERE j.status = 'reviewing' AND j.review_claimed = 0
            AND NOT EXISTS (
                SELECT 1 FROM annotations a
                JOIN analysis_results ar ON a.analysis_result_id = ar.id
                JOIN utterances u ON ar.utterance_id = u.id
                WHERE u.job_id = j.id AND a.fact_check_status IN ('pending', 'processing')
            )
            LIMIT 1
        """).fetchone()
        if not row:
            return None
        cursor = conn.execute(
            "UPDATE jobs SET review_claimed = 1, updated_at = datetime('now') "
            "WHERE id = ? AND review_claimed = 0",
            (row["id"],),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return self._row_to_job(row)

    def complete_review(self, job_id: JobId, findings_json: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO transcript_reviews (job_id, findings_json) VALUES (?, ?)",
            (job_id, findings_json),
        )
        conn.commit()

    def get_review(self, job_id: JobId) -> dict | None:
        row = self._get_conn().execute(
            "SELECT findings_json FROM transcript_reviews WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        return json.loads(row["findings_json"])

    def get_all_analysed_texts(self, job_id: JobId) -> list[AnalysedText]:
        utterances = self.get_utterances(job_id)
        results = []
        for utt in utterances:
            if utt.analysis_status != AnalysisStatus.COMPLETE:
                continue
            parts = self.get_analysed_parts(utt.id)
            if not parts:
                continue
            results.append(AnalysedText(
                utterance_id=utt.id,
                text=utt.text,
                analysed_parts=tuple(parts),
                remainder=utt.analysis_remainder,
            ))
        return results

    # -- Rate Limits --

    def get_rate_limit(self, model: str) -> dict | None:
        row = self._get_conn().execute(
            "SELECT retry_after, backoff_level FROM rate_limits WHERE model = ?", (model,)
        ).fetchone()
        if not row:
            return None
        return {"retry_after": row["retry_after"], "backoff_level": row["backoff_level"]}

    def set_rate_limit(self, model: str, retry_after: float, backoff_level: int) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO rate_limits (model, retry_after, backoff_level, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(model) DO UPDATE SET
                   retry_after = excluded.retry_after,
                   backoff_level = excluded.backoff_level,
                   updated_at = datetime('now')""",
            (model, retry_after, backoff_level),
        )
        conn.commit()

    def clear_rate_limit(self, model: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM rate_limits WHERE model = ?", (model,))
        conn.commit()

    # -- Work Item Reset --

    def reset_utterance_to_pending(self, utterance_id: UtteranceId) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE utterances SET analysis_status = 'pending' WHERE id = ? AND analysis_status = 'processing'",
            (utterance_id,),
        )
        conn.commit()

    def reset_fact_check_to_pending(self, annotation_id: AnnotationId) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE annotations SET fact_check_status = 'pending' WHERE id = ? AND fact_check_status = 'processing'",
            (annotation_id,),
        )
        conn.commit()

    def reset_review_claim(self, job_id: JobId) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE jobs SET review_claimed = 0 WHERE id = ? AND review_claimed = 1",
            (job_id,),
        )
        conn.commit()

    # -- Recovery --

    def recover_incomplete_work(self) -> None:
        """Reset any in-progress or failed items back to pending so they are retried."""
        conn = self._get_conn()
        conn.execute("UPDATE utterances SET analysis_status = 'pending' WHERE analysis_status IN ('processing', 'failed')")
        conn.execute("UPDATE annotations SET fact_check_status = 'pending' WHERE fact_check_status IN ('processing', 'failed')")
        conn.execute("""
            UPDATE jobs SET review_claimed = 0
            WHERE review_claimed = 1 AND status = 'reviewing'
            AND id NOT IN (SELECT job_id FROM transcript_reviews)
        """)
        # Pull jobs back to the correct stage if they advanced past reset work
        conn.execute("""
            UPDATE jobs SET status = 'analysing', review_claimed = 0, updated_at = datetime('now')
            WHERE status IN ('reviewing', 'complete') AND id IN (
                SELECT DISTINCT u.job_id FROM utterances u
                WHERE u.analysis_status = 'pending'
            )
        """)
        conn.execute("""
            UPDATE jobs SET status = 'reviewing', review_claimed = 0, updated_at = datetime('now')
            WHERE status = 'complete' AND id IN (
                SELECT DISTINCT u.job_id FROM annotations a
                JOIN analysis_results ar ON a.analysis_result_id = ar.id
                JOIN utterances u ON ar.utterance_id = u.id
                WHERE a.fact_check_status = 'pending'
            )
        """)
        conn.commit()
        log.info("Recovered any in-progress or failed work items")
