// ── Toothcomb — Job Store ──

import {buildEmitter} from './events';
import {
    JobStore,
    JobMeta,
    JobConfig,
    JobContext,
    ActiveJob,
    StatCounts,
    VerdictCounts,
    SourceType,
    StreamingMode,
    JobCreatedEvent,
    JobStatusEvent,
    JobDeletedEvent,
    TranscriptionEvent,
    AnalysisEvent,
    UtterancesMergedEvent,
    FactCheckEvent,
    FactCheckResetEvent,
    JobStatsEvent,
    ReplayCompleteEvent,
    ReviewData,
} from './types';

export function buildJobStore(): JobStore {
    const {on, emit} = buildEmitter();
    let jobs: JobMeta[] = [],
        activeJobId: string | null = null,
        activeJob: ActiveJob | null = null,
        selectedRef: string | null = null,
        activeFindingRefs: string[] | null = null;

    function arraysEqual(a: string[] | null, b: string[] | null): boolean {
        if (a === b) return true;
        if (!a || !b) return false;
        if (a.length !== b.length) return false;
        return a.every((v, i) => v === b[i]);
    }

    function makeActiveJob(): ActiveJob {
        return {utterances: {}, analysis: {}, factChecks: {}, pendingMerges: {}, stats: [], review: null, status: 'init'};
    }

    function selectJob(jobId: string): void {
        activeJobId = jobId;
        activeJob = makeActiveJob();
        selectedRef = null;
        activeFindingRefs = null;
        emit('navChanged');
        emit('changed');
        emit('selectionChanged');
    }

    // ── Selection state (view state held centrally so it survives renders) ──
    function getSelectedRef(): string | null {
        return selectedRef;
    }

    function getActiveFindingRefs(): string[] | null {
        return activeFindingRefs;
    }

    function setSelection(ref: string | null): void {
        if (selectedRef === ref && activeFindingRefs === null) {
            return;
        }
        selectedRef = ref;
        activeFindingRefs = null;
        emit('selectionChanged');
    }

    function setActiveFinding(refs: string[] | null): void {
        if (arraysEqual(activeFindingRefs, refs) && selectedRef === null) {
            return;
        }
        activeFindingRefs = refs;
        selectedRef = null;
        emit('selectionChanged');
    }

    function clearSelection(): void {
        if (selectedRef === null && activeFindingRefs === null) {
            return;
        }
        selectedRef = null;
        activeFindingRefs = null;
        emit('selectionChanged');
    }

    function getActiveJobId(): string | null {
        return activeJobId;
    }

    function getActiveJob(): ActiveJob | null {
        return activeJob;
    }

    function getJobs(): JobMeta[] {
        return jobs;
    }

    function setJobs(list: JobMeta[]): void {
        jobs = list;
        emit('navChanged');
    }

    function parseConfig(job: JobMeta | undefined): JobConfig {
        if (!job || !job.config) {
            return {};
        }
        try {
            return typeof job.config === 'string' ? JSON.parse(job.config) : job.config;
        } catch {
            return {};
        }
    }

    function getJobContext(jobMeta: JobMeta | undefined): JobContext {
        return parseConfig(jobMeta).context || {};
    }

    function getJobSourceType(jobId: string): SourceType | undefined {
        const cfg = parseConfig(jobs.find(j => j.id === jobId));
        return cfg.source && cfg.source.type;
    }

    function getJobStreamingMode(jobId: string): StreamingMode | undefined {
        const cfg = parseConfig(jobs.find(j => j.id === jobId));
        return cfg.source && cfg.source.streaming_mode;
    }

    function countStats(): StatCounts {
        const counts = {claims: 0, predictions: 0, commitments: 0, fallacies: 0, rhetoric: 0, tactics: 0},
            verdicts: VerdictCounts = {established: 0, misleading: 0, unsupported: 0, false: 0, pending: 0, failed: 0};

        if (!activeJob) {
            return {...counts, verdicts};
        }

        Object.values(activeJob!.analysis).forEach(a => {
            (a.parts || []).forEach(p => {
                (p.annotations || []).forEach(ann => {
                    if (ann.type === 'CLAIM') {
                        counts.claims++;
                    } else if (ann.type === 'PREDICTION') {
                        counts.predictions++;
                    } else if (ann.type === 'COMMITMENT') {
                        counts.commitments++;
                    } else if (ann.type === 'FALLACY') {
                        counts.fallacies++;
                    } else if (ann.type === 'RHETORIC') {
                        counts.rhetoric++;
                    } else if (ann.type === 'TACTIC') {
                        counts.tactics++;
                    }

                    const fc = activeJob!.factChecks[ann.annotation_id];
                    if (fc) {
                        const v = fc.verdict.toLowerCase() as keyof VerdictCounts;
                        if (verdicts.hasOwnProperty(v)) {
                            verdicts[v]++;
                        }
                    } else if (ann.fact_check_query) {
                        verdicts.pending++;
                    }
                });
            });
        });

        return {...counts, verdicts};
    }

    // ── Service event mutations ──
    function handleJobCreated(data: JobCreatedEvent): void {
        if (!jobs.find(j => j.id === data.id)) {
            jobs.unshift(data);
            emit('navChanged');
        }
    }

    function handleJobStatus(data: JobStatusEvent): void {
        if (data.job_id === activeJobId && activeJob) {
            activeJob.status = data.status;
            emit('changed');
        }
        const job = jobs.find(j => j.id === data.job_id);
        if (job) {
            job.status = data.status;
        }
        emit('navChanged');
    }

    function handleJobDeleted(data: JobDeletedEvent): void {
        jobs = jobs.filter(j => j.id !== data.job_id);
        if (activeJobId === data.job_id) {
            activeJobId = null;
            activeJob = null;
        }
        emit('navChanged');
        emit('changed');
    }

    function handleTranscription(data: TranscriptionEvent): void {
        if (data.job_id === activeJobId && activeJob) {
            activeJob.utterances[data.utterance_id] = data;
            emit('changed');
        }
    }

    function handleAnalysis(data: AnalysisEvent): void {
        if (data.job_id === activeJobId && activeJob) {
            activeJob.analysis[data.utterance_id] = data;
            const merged = activeJob.pendingMerges[data.utterance_id];
            if (merged) {
                merged.forEach(id => delete activeJob!.utterances[id]);
                delete activeJob.pendingMerges[data.utterance_id];
            }
            emit('changed');
        }
    }

    function handleUtterancesMerged(data: UtterancesMergedEvent): void {
        if (data.job_id === activeJobId && activeJob) {
            activeJob.pendingMerges[data.target_id] = data.merged_ids || [];
        }
    }

    function handleFactCheck(data: FactCheckEvent): void {
        if (data.job_id === activeJobId && activeJob) {
            activeJob.factChecks[data.annotation_id] = data;
            emit('changed');
        }
    }

    function handleFactCheckReset(data: FactCheckResetEvent): void {
        if (data.job_id === activeJobId && activeJob) {
            delete activeJob.factChecks[data.annotation_id];
            emit('changed');
        }
    }

    function handleJobStats(data: JobStatsEvent): void {
        if (data.job_id === activeJobId && activeJob) {
            activeJob.stats = data.stats;
            emit('statsChanged');
        }
    }

    function handleReview(data: ReviewData): void {
        if (data.job_id === activeJobId && activeJob) {
            activeJob.review = data;
            emit('changed');
        }
    }

    function handleReplayComplete(data: ReplayCompleteEvent): void {
        if (data.job_id === activeJobId && activeJob) {
            emit('changed');
        }
    }

    return {
        on,
        getJobs,
        setJobs,
        getActiveJobId,
        getActiveJob,
        selectJob,
        getJobContext,
        getJobSourceType,
        getJobStreamingMode,
        countStats,
        getSelectedRef,
        getActiveFindingRefs,
        setSelection,
        setActiveFinding,
        clearSelection,
        handleJobCreated,
        handleJobStatus,
        handleJobDeleted,
        handleTranscription,
        handleAnalysis,
        handleUtterancesMerged,
        handleFactCheck,
        handleFactCheckReset,
        handleJobStats,
        handleReview,
        handleReplayComplete,
    };
}
