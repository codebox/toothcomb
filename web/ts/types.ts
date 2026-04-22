// ── Toothcomb — Shared Types ──

// ── Domain Enums ──

export type AnnotationType = 'CLAIM' | 'PREDICTION' | 'COMMITMENT' | 'FALLACY' | 'RHETORIC' | 'TACTIC';

export type Verdict = 'Established' | 'Misleading' | 'Unsupported' | 'False' | 'Pending' | 'FAILED';

export type JobStatus = 'init' | 'ingesting' | 'analysing' | 'reviewing' | 'complete' | 'aborted';

export type SourceType = 'text' | 'mp3' | 'streaming';

export type StreamingMode = 'mic' | 'play-mp3';

// ── Domain Models ──

export interface Annotation {
    annotation_id: string;
    type: AnnotationType;
    notes: string;
    fact_check_query?: string;
    fact_check_status?: string | null;
    _refNum?: number;
}

export interface AnalysisPart {
    corrected_text: string;
    annotations?: Annotation[];
}

export interface AnalysisResult {
    utterance_id: string;
    job_id: string;
    parts?: AnalysisPart[];
    remainder?: string;
    failed?: boolean;
}

export interface Utterance {
    utterance_id: string;
    job_id: string;
    text: string;
    seq: number;
    speaker?: string;
}

export interface FactCheckCitation {
    url: string;
    title: string;
}

export interface FactCheck {
    job_id: string;
    annotation_id: string;
    verdict: Verdict;
    note: string;
    citations?: FactCheckCitation[];
}

export interface LlmStatItem {
    model: string;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_creation_tokens: number;
}

export interface JobContext {
    speakers?: string;
    date_and_time?: string;
    location?: string;
    background?: string;
}

export interface JobSource {
    type: SourceType;
    text?: string;
    original_filename?: string;
    streaming_mode?: StreamingMode;
}

export interface JobConfig {
    context?: JobContext;
    source?: JobSource;
}

export interface JobMeta {
    id: string;
    title?: string;
    status?: string;
    config?: string;
}

// ── Review Findings ──

export interface ReviewFinding {
    id: string;
    type: string;
    technique: string;
    summary: string;
    refs: string[];
    excerpt?: string;
}

export interface ReviewData {
    job_id: string;
    findings: ReviewFinding[];
    failed: boolean;
}

// ── Active Job State ──

export interface ActiveJob {
    utterances: Record<string, Utterance>;
    analysis: Record<string, AnalysisResult>;
    factChecks: Record<string, FactCheck>;
    pendingMerges: Record<string, string[]>;
    stats: LlmStatItem[];
    review: ReviewData | null;
    status: JobStatus;
}

// ── Stat Counts ──

export interface VerdictCounts {
    established: number;
    misleading: number;
    unsupported: number;
    false: number;
    pending: number;
    failed: number;
}

export interface StatCounts {
    claims: number;
    predictions: number;
    commitments: number;
    fallacies: number;
    rhetoric: number;
    tactics: number;
    verdicts: VerdictCounts;
}

// ── Server Events (incoming) ──

export interface JobCreatedEvent {
    id: string;
    title?: string;
    status?: string;
    config?: string;
}

export interface JobStatusEvent {
    job_id: string;
    status: JobStatus;
}

export interface JobDeletedEvent {
    job_id: string;
}

export interface TranscriptionEvent {
    job_id: string;
    utterance_id: string;
    text: string;
    seq: number;
    speaker?: string;
}

export interface AnalysisEvent {
    job_id: string;
    utterance_id: string;
    parts?: AnalysisPart[];
    remainder?: string;
    failed?: boolean;
}

export interface UtterancesMergedEvent {
    job_id: string;
    target_id: string;
    merged_ids: string[];
}

export interface FactCheckEvent {
    job_id: string;
    annotation_id: string;
    verdict: Verdict;
    note: string;
    citations?: FactCheckCitation[];
}

export interface FactCheckResetEvent {
    job_id: string;
    annotation_id: string;
}

export interface JobStatsEvent {
    job_id: string;
    stats: LlmStatItem[];
}

export interface ReplayCompleteEvent {
    job_id: string;
}

// ── Client Payloads ──

export interface CreateJobPayload {
    title: string;
    context: JobContext;
    source: JobSource;
}

export interface CreateJobResponse {
    job_id: string;
}

// ── Modal Form ──

export interface TranscriptFormData {
    tab: string;
    title: string;
    speakers: string;
    datetime: string;
    location: string;
    background: string;
    transcript: string;
    mp3File: File | null;
    playMp3File: File | null;
}

// ── Audio Info ──

export interface AudioInfo {
    active: boolean;
    paused: boolean;
    jobId: string | null;
    label?: string;
    seconds: number;
}

// ── Audio Callbacks ──

export interface AudioCallbacks {
    onRender(): void;
    onMicrophoneRequested(): void;
    onRecordingTick(seconds: number): void;
    onVisualizerFrame(dataArray: Uint8Array, barCount: number): void;
}

// ── Emitter ──

export interface Emitter {
    on(event: string, fn: (data?: any) => void): void;
    emit(event: string, data?: any): void;
}

// ── View Interfaces ──

export interface NavView {
    on(event: string, fn: (data?: any) => void): void;
    render(jobs: JobMeta[], activeJobId: string | null): void;
}

export interface SummaryData {
    title: string;
    status: string;
    context: JobContext;
    stats: StatCounts;
    verdicts: VerdictCounts;
    llmStats: LlmStatItem[];
}

export interface SummaryView {
    on(event: string, fn: (data?: any) => void): void;
    render(data: SummaryData | null): void;
}

export interface TranscriptData {
    utterances: Utterance[];
    analysis: Record<string, AnalysisResult>;
    factChecks: Record<string, FactCheck>;
    status: string;
    context: JobContext;
    jobId: string;
    audio: AudioInfo;
    isStreaming: boolean;
    rateLimited: boolean;
}

export interface TranscriptView {
    on(event: string, fn: (data?: any) => void): void;
    render(data: TranscriptData | null): void;
    updateRecordingTime(seconds: number): void;
    updateVisualizer(dataArray: Uint8Array, barCount: number): void;
    showMicrophonePrompt(): void;
}

export interface MarginaliaData {
    utterances: Utterance[];
    analysis: Record<string, AnalysisResult>;
    factChecks: Record<string, FactCheck>;
    review: ReviewData | null;
    status: string;
    demo: boolean;
}

export interface MarginaliaView {
    on(event: string, fn: (data?: any) => void): void;
    render(data: MarginaliaData | null): void;
}

export interface AnnotationView {
    setup(): void;
    selectRef(ref: string | null): void;
}

export interface ModalView {
    on(event: string, fn: (data?: any) => void): void;
    open(): void;
    close(): void;
}

export interface ConfirmModal {
    on(event: string, fn: (data?: any) => void): void;
    open(...args: any[]): void;
    close(): void;
}

export interface AppView {
    nav: NavView;
    summary: SummaryView;
    transcript: TranscriptView;
    marginalia: MarginaliaView;
    annotations: AnnotationView;
    modal: ModalView;
    deleteModal: ConfirmModal;
    abortModal: ConfirmModal;
}

// ── Service ──

export interface Service {
    on(event: string, fn: (data?: any) => void): void;
    loadJobs(): Promise<JobMeta[]>;
    createJob(payload: CreateJobPayload, mp3File?: File): Promise<CreateJobResponse>;
    startJob(jobId: string): Promise<void>;
    abortJob(jobId: string): Promise<void>;
    deleteJob(jobId: string): Promise<void>;
    retryFactCheck(jobId: string, annotationId: string): Promise<void>;
    joinJob(jobId: string): void;
    leaveJob(jobId: string): void;
    sendAudioChunk(jobId: string, audioBuffer: ArrayBuffer): void;
    stopAudio(jobId: string): void;
}

// ── Store ──

export interface JobStore {
    on(event: string, fn: (data?: any) => void): void;
    getJobs(): JobMeta[];
    setJobs(list: JobMeta[]): void;
    getActiveJobId(): string | null;
    getActiveJob(): ActiveJob | null;
    selectJob(jobId: string): void;
    getJobContext(jobMeta: JobMeta | undefined): JobContext;
    getJobSourceType(jobId: string): SourceType | undefined;
    getJobStreamingMode(jobId: string): StreamingMode | undefined;
    countStats(): StatCounts;
    getSelectedRef(): string | null;
    getActiveFindingRefs(): string[] | null;
    setSelection(ref: string | null): void;
    setActiveFinding(refs: string[] | null): void;
    clearSelection(): void;
    handleJobCreated(data: JobCreatedEvent): void;
    handleJobStatus(data: JobStatusEvent): void;
    handleJobDeleted(data: JobDeletedEvent): void;
    handleTranscription(data: TranscriptionEvent): void;
    handleAnalysis(data: AnalysisEvent): void;
    handleUtterancesMerged(data: UtterancesMergedEvent): void;
    handleFactCheck(data: FactCheckEvent): void;
    handleFactCheckReset(data: FactCheckResetEvent): void;
    handleJobStats(data: JobStatsEvent): void;
    handleReview(data: ReviewData): void;
    handleReplayComplete(data: ReplayCompleteEvent): void;
}

// ── Audio Pipeline ──

export interface AudioPipeline {
    handleStartStreaming(jobId: string): Promise<void>;
    handleStartStreamingMp3(jobId: string): Promise<void>;
    stopStreaming(): void;
    pauseAudio(): void;
    resumeAudio(): void;
    selectStreamMp3(file: File): void;
    getAudioInfo(): AudioInfo;
    getStreamMp3Name(): string | null;
}
