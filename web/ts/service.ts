// ── Toothcomb — Service Layer ──
// Encapsulates all server communication (Socket.IO + fetch).
// No DOM interaction or business logic.

import {io} from 'socket.io-client';
import {buildEmitter} from './events';
import type {Service, CreateJobPayload, CreateJobResponse, JobMeta} from './types';

export function buildService(): Service {
    const socket = io(),
        {on, emit} = buildEmitter();

    // ── Socket.IO → service events ──
    socket.on('job_created', (data: any) => emit('jobCreated', data));
    socket.on('job_status', (data: any) => emit('jobStatus', data));
    socket.on('job_deleted', (data: any) => emit('jobDeleted', data));
    socket.on('transcription', (data: any) => emit('transcription', data));
    socket.on('analysis', (data: any) => emit('analysis', data));
    socket.on('utterances_merged', (data: any) => emit('utterancesMerged', data));
    socket.on('fact_check', (data: any) => emit('factCheck', data));
    socket.on('fact_check_reset', (data: any) => emit('factCheckReset', data));
    socket.on('job_stats', (data: any) => emit('jobStats', data));
    socket.on('transcript_review', (data: any) => emit('transcriptReview', data));
    socket.on('replay_complete', (data: any) => emit('replayComplete', data));
    socket.on('rate_limited', (data: any) => emit('rateLimited', data));

    // ── REST API ──
    async function loadJobs(): Promise<JobMeta[]> {
        const resp = await fetch('/api/jobs');
        if (!resp.ok) {
            throw new Error(await resp.text());
        }
        return resp.json();
    }

    async function createJob(payload: CreateJobPayload, mp3File?: File): Promise<CreateJobResponse> {
        let resp: Response;
        if (mp3File) {
            const fd = new FormData();
            fd.append('data', JSON.stringify(payload));
            fd.append('file', mp3File);
            resp = await fetch('/jobs', {method: 'POST', body: fd});
        } else {
            resp = await fetch('/jobs', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
        }
        if (!resp.ok) {
            throw new Error(await resp.text());
        }
        return resp.json();
    }

    async function startJob(jobId: string): Promise<void> {
        const resp = await fetch(`/jobs/${jobId}/start`, {method: 'POST'});
        if (!resp.ok) {
            throw new Error(await resp.text());
        }
    }

    async function abortJob(jobId: string): Promise<void> {
        const resp = await fetch(`/jobs/${jobId}/abort`, {method: 'POST'});
        if (!resp.ok) {
            throw new Error(await resp.text());
        }
    }

    async function deleteJob(jobId: string): Promise<void> {
        const resp = await fetch(`/jobs/${jobId}`, {method: 'DELETE'});
        if (!resp.ok) {
            throw new Error(await resp.text());
        }
    }

    async function retryFactCheck(jobId: string, annotationId: string): Promise<void> {
        const resp = await fetch(
            `/jobs/${jobId}/annotations/${annotationId}/retry-fact-check`,
            {method: 'POST'},
        );
        if (!resp.ok) {
            throw new Error(await resp.text());
        }
    }

    // ── Socket commands ──
    function joinJob(jobId: string): void {
        socket.emit('join_job', {job_id: jobId});
    }

    function leaveJob(jobId: string): void {
        socket.emit('leave_job', {job_id: jobId});
    }

    function sendAudioChunk(jobId: string, audioBuffer: ArrayBuffer): void {
        socket.emit('audio_chunk', {job_id: jobId, audio: audioBuffer});
    }

    function stopAudio(jobId: string): void {
        socket.emit('audio_stop', {job_id: jobId});
    }

    return {
        on,
        loadJobs,
        createJob,
        startJob,
        abortJob,
        deleteJob,
        retryFactCheck,
        joinJob,
        leaveJob,
        sendAudioChunk,
        stopAudio,
    };
}
