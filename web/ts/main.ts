// ── Toothcomb — App ──

import {buildView} from './view/index';
import {buildService} from './service';
import {buildJobStore} from './store';
import {buildAudioPipeline} from './audio';
import {TranscriptFormData, CreateJobPayload, JobSource} from './types';

document.addEventListener('DOMContentLoaded', () => {

    const demo = document.querySelector('meta[name="demo"]')?.getAttribute('content') === 'true',
        service = buildService(),
        {nav, summary, transcript, marginalia, annotations, modal, deleteModal, abortModal} = buildView(),
        store = buildJobStore(),
        audio = buildAudioPipeline(service, {
            onRender: () => render(),
            onRecordingTick: seconds => transcript.updateRecordingTime(seconds),
            onVisualizerFrame: (dataArray, barCount) => transcript.updateVisualizer(dataArray, barCount),
        });

    // ── Rate limit state ──
    let rateLimitUntil = 0,
        rateLimitTimer: ReturnType<typeof setTimeout> | null = null;

    function showRateLimitNotice(retryInSeconds: number) {
        rateLimitUntil = Date.now() + retryInSeconds * 1000;
        render();
        if (rateLimitTimer) {
            clearTimeout(rateLimitTimer);
        }
        rateLimitTimer = setTimeout(() => {
            rateLimitUntil = 0;
            rateLimitTimer = null;
            render();
        }, (retryInSeconds + 2) * 1000);
    }

    // ── Load job list ──
    async function loadJobs() {
        try {
            store.setJobs(await service.loadJobs());
        } catch (e: any) { /* API unavailable */ }
        nav.render(store.getJobs(), store.getActiveJobId());
    }

    // ── Job selection ──
    function selectJob(jobId: string, pushHistory: boolean = true) {
        if (!store.getJobs().find(j => j.id === jobId)) {
            return;
        }
        const prevId = store.getActiveJobId();
        if (prevId) {
            service.leaveJob(prevId);
        }
        store.selectJob(jobId);
        service.joinJob(jobId);
        if (pushHistory) {
            history.pushState(null, '', '#' + jobId);
        }
    }

    // ── Service events → store mutations ──
    service.on('jobCreated', data => store.handleJobCreated(data));
    service.on('jobStatus', data => store.handleJobStatus(data));
    service.on('jobDeleted', data => store.handleJobDeleted(data));
    service.on('transcription', data => store.handleTranscription(data));
    service.on('analysis', data => store.handleAnalysis(data));
    service.on('utterancesMerged', data => store.handleUtterancesMerged(data));
    service.on('factCheck', data => store.handleFactCheck(data));
    service.on('jobStats', data => store.handleJobStats(data));
    service.on('transcriptReview', data => store.handleReview(data));
    service.on('replayComplete', data => store.handleReplayComplete(data));
    service.on('rateLimited', (data: any) => {
        if (data.job_id === store.getActiveJobId()) {
            showRateLimitNotice(data.retry_in_seconds);
        }
    });

    // ── Store events → view renders ──
    store.on('changed', () => render());
    store.on('navChanged', () => nav.render(store.getJobs(), store.getActiveJobId()));
    store.on('statsChanged', () => renderSummary());

    // ── Nav events ──
    nav.on('selectJob', selectJob);
    nav.on('openModal', () => modal.open());

    // ── Demo mode message ──
    const DEMO_MSG = 'This is a demo — this action is not available.';

    // ── Modal events ──
    modal.on('submitTranscript', (formData: TranscriptFormData) => {
        if (demo) {
            alert(DEMO_MSG);
            return;
        }
        handleSubmitTranscript(formData);
    });

    // ── Summary events ──
    summary.on('deleteJob', () => {
        if (demo) {
            alert(DEMO_MSG);
            return;
        }
        const jobId = store.getActiveJobId();
        if (!jobId) {
            return;
        }
        const jobMeta = store.getJobs().find(j => j.id === jobId);
        deleteModal.open(jobId, jobMeta && jobMeta.title);
    });

    // ── Delete modal events ──
    deleteModal.on('confirmDelete', handleDeleteJob);

    // ── Transcript events ──
    transcript.on('startJob', (jobId: string) => {
        if (demo) {
            alert(DEMO_MSG);
            return;
        }
        handleStartJob(jobId);
    });
    transcript.on('pauseAudio', () => audio.pauseAudio());
    transcript.on('resumeAudio', () => audio.resumeAudio());
    transcript.on('stopStreaming', () => audio.stopStreaming());
    transcript.on('abortJob', () => {
        if (demo) {
            alert(DEMO_MSG);
            return;
        }
        abortModal.open();
    });

    // ── Abort modal events ──
    abortModal.on('confirmAbort', handleAbortJob);

    // ── Main render ──
    function render() {
        renderSummary();
        renderTranscript();
        renderMarginalia();
        annotations.setup();
    }

    // ── Summary ──
    function renderSummary() {
        const activeJob = store.getActiveJob(),
            activeJobId = store.getActiveJobId();

        if (!activeJob) {
            summary.render(null);
            return;
        }

        const jobMeta = store.getJobs().find(j => j.id === activeJobId),
            context = store.getJobContext(jobMeta),
            stats = store.countStats(),
            llmStats = activeJob.stats || [];

        summary.render({
            title: (jobMeta && jobMeta.title) || activeJobId || '',
            status: activeJob.status || 'init',
            context,
            stats,
            verdicts: stats.verdicts,
            llmStats,
        });
    }

    // ── Transcript ──
    function renderTranscript() {
        const activeJob = store.getActiveJob(),
            activeJobId = store.getActiveJobId();

        if (!activeJob) {
            transcript.render(null);
            return;
        }

        const jobMeta = store.getJobs().find(j => j.id === activeJobId),
            context = store.getJobContext(jobMeta),
            utterances = Object.values(activeJob.utterances).sort((a, b) => a.seq - b.seq);

        transcript.render({
            utterances,
            analysis: activeJob.analysis,
            factChecks: activeJob.factChecks,
            status: activeJob.status || 'init',
            context,
            jobId: activeJobId!,
            audio: audio.getAudioInfo(),
            isStreaming: store.getJobSourceType(activeJobId!) === 'streaming',
            rateLimited: Date.now() < rateLimitUntil,
        });
    }

    // ── Marginalia ──
    function renderMarginalia() {
        const activeJob = store.getActiveJob();

        if (!activeJob) {
            marginalia.render(null);
            return;
        }

        const utterances = Object.values(activeJob.utterances).sort((a, b) => a.seq - b.seq);

        marginalia.render({
            utterances,
            analysis: activeJob.analysis,
            factChecks: activeJob.factChecks,
            review: activeJob.review,
            status: activeJob.status || 'init',
        });
    }

    // ── API actions ──
    async function handleStartJob(jobId: string) {
        try {
            const sourceType = store.getJobSourceType(jobId),
                streamingMode = store.getJobStreamingMode(jobId);
            if (sourceType === 'streaming' && streamingMode === 'play-mp3') {
                await audio.handleStartStreamingMp3(jobId);
            } else if (sourceType === 'streaming') {
                await audio.handleStartStreaming(jobId);
            } else {
                await service.startJob(jobId);
            }
        } catch (e: any) {
            alert('Failed to start job: ' + e.message);
        }
    }

    async function handleAbortJob() {
        const jobId = store.getActiveJobId();
        if (!jobId) {
            return;
        }
        try {
            await service.abortJob(jobId);
            audio.stopStreaming();
        } catch (e: any) {
            alert('Failed to stop job: ' + e.message);
        }
    }

    async function handleDeleteJob(jobId: string) {
        try {
            await service.deleteJob(jobId);
        } catch (e: any) {
            alert('Failed to delete job: ' + e.message);
        }
    }

    async function handleSubmitTranscript(formData: TranscriptFormData) {
        if (!formData.title) {
            alert('Please provide a title.');
            return;
        }

        const payload: CreateJobPayload = {
            title: formData.title,
            context: {
                speakers: formData.speakers,
                date_and_time: formData.datetime,
                location: formData.location,
                background: formData.background,
            },
            source: {type: formData.tab} as JobSource,
        };

        if (formData.tab === 'text') {
            if (!formData.transcript.trim()) {
                alert('Please paste the transcript text.');
                return;
            }
            payload.source.type = 'text';
            payload.source.text = formData.transcript;
        } else if (formData.tab === 'mp3') {
            if (!formData.mp3File) {
                alert('Please select an MP3 file.');
                return;
            }
            payload.source.original_filename = formData.mp3File.name;
        } else if (formData.tab === 'play-mp3') {
            if (!formData.playMp3File) {
                alert('Please select an MP3 file.');
                return;
            }
            payload.source.type = 'streaming';
            payload.source.streaming_mode = 'play-mp3';
            audio.selectStreamMp3(formData.playMp3File);
        } else if (formData.tab === 'mic') {
            payload.source.type = 'streaming';
            payload.source.streaming_mode = 'mic';
        }

        try {
            const result = await service.createJob(payload, formData.mp3File ?? undefined);
            modal.close();
            selectJob(result.job_id);
        } catch (e: any) {
            alert('Error creating job: ' + e.message);
        }
    }

    // ── URL hash navigation ──
    function jobIdFromHash(): string {
        return location.hash.slice(1).split('/')[0];
    }

    window.addEventListener('popstate', () => {
        const jobId = jobIdFromHash(),
            ref = location.hash.slice(1).split('/')[1] || null;
        if (jobId && jobId !== store.getActiveJobId()) {
            // Different job — full reload, setup() will restore ref from hash
            selectJob(jobId, false);
        } else {
            // Same job — just switch annotation without DOM rebuild
            annotations.selectRef(ref);
        }
    });

    // ── Init ──
    async function init() {
        await loadJobs();
        const jobId = jobIdFromHash();
        if (jobId) {
            selectJob(jobId, false);
        }
    }

    init();

}); // DOMContentLoaded
