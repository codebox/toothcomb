// ── Toothcomb — Audio Pipeline ──

import {Service, AudioPipeline, AudioInfo, AudioCallbacks} from './types';

interface AudioState {
    jobId: string | null;
    active: boolean;
    paused: boolean;
    context: AudioContext | null;
    processor: ScriptProcessorNode | null;
    analyser?: AnalyserNode;
    audioSource?: AudioNode;
    nativeSampleRate?: number;
    stream?: MediaStream | null;
    audioEl?: HTMLAudioElement | null;
    label?: string;
    vizFrame?: number | null;
    timer?: ReturnType<typeof setInterval> | null;
    seconds: number;
    buf?: {samples: number[]; count: number};
}

const STREAM_SAMPLE_RATE = 16000,
    STREAM_CHUNK_SECONDS = 5;

export function buildAudioPipeline(service: Service, callbacks: AudioCallbacks): AudioPipeline {
    let audioState: AudioState = {jobId: null, active: false, paused: false, context: null, processor: null, timer: null, seconds: 0},
        streamMp3File: File | null = null;

    function sendAudioChunk(jobId: string, floatSamples: number[], sourceSampleRate: number): void {
        let samples = floatSamples;
        if (sourceSampleRate !== STREAM_SAMPLE_RATE) {
            const ratio = sourceSampleRate / STREAM_SAMPLE_RATE,
                outLen = Math.round(floatSamples.length / ratio);
            samples = new Array(outLen) as number[];
            for (let i = 0; i < outLen; i++) {
                samples[i] = floatSamples[Math.round(i * ratio)];
            }
        }
        const int16 = new Int16Array(samples.length);
        for (let i = 0; i < samples.length; i++) {
            const s = Math.max(-1, Math.min(1, samples[i]));
            int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        service.sendAudioChunk(jobId, int16.buffer);
    }

    function startVisualizer() {
        const barCount = 24;

        function draw() {
            if (!audioState.active) {
                return;
            }
            audioState.vizFrame = requestAnimationFrame(draw);
            const analyser = audioState.analyser,
                dataArray = new Uint8Array(analyser!.frequencyBinCount);
            analyser!.getByteFrequencyData(dataArray);
            callbacks.onVisualizerFrame(dataArray, barCount);
        }

        draw();
    }

    function startAudioPipeline(jobId: string, context: AudioContext, source: AudioNode, extras: {stream?: MediaStream; audioEl?: HTMLAudioElement; label?: string}): void {
        const nativeSampleRate = context.sampleRate,
            bufferSize = Math.round(nativeSampleRate * STREAM_CHUNK_SECONDS),
            processor = context.createScriptProcessor(4096, 1, 1),
            buf = {samples: [] as number[], count: 0};

        processor.onaudioprocess = function (e: AudioProcessingEvent) {
            if (audioState.paused) {
                return;
            }
            const input = e.inputBuffer.getChannelData(0);
            for (let i = 0; i < input.length; i++) {
                buf.samples.push(input[i]);
                buf.count++;
                if (buf.count >= bufferSize) {
                    sendAudioChunk(jobId, buf.samples, nativeSampleRate);
                    buf.samples = [];
                    buf.count = 0;
                }
            }
        };

        const analyser = context.createAnalyser();
        analyser.fftSize = 64;

        source.connect(analyser);
        source.connect(processor);
        processor.connect(context.destination);

        if (extras.audioEl) {
            source.connect(context.destination);
        }

        audioState = {
            jobId, active: true, paused: false, context, processor, analyser,
            audioSource: source, nativeSampleRate, buf,
            stream: extras.stream || null,
            audioEl: extras.audioEl || null,
            label: extras.label,
            vizFrame: null,
            timer: setInterval(() => {
                audioState.seconds++;
                callbacks.onRecordingTick(audioState.seconds);
            }, 1000),
            seconds: 0,
        };

        startVisualizer();
        streamMp3File = null;
        callbacks.onRender();
    }

    async function handleStartStreaming(jobId: string) {
        let stream: MediaStream | undefined;
        let context: AudioContext | undefined;
        try {
            callbacks.onMicrophoneRequested();
            stream = await navigator.mediaDevices.getUserMedia({audio: true});
            context = new AudioContext();
            if (context.state === 'suspended') {
                await context.resume();
            }
            const source = context.createMediaStreamSource(stream);
            await service.startJob(jobId);
            startAudioPipeline(jobId, context, source, {stream: stream, label: 'microphone'});
        } catch (e: any) {
            if (stream) {
                stream.getTracks().forEach(t => t.stop());
            }
            if (context) {
                context.close();
            }
            callbacks.onRender();
            if (e.name === 'NotAllowedError') {
                alert('Microphone access was denied. To allow it, click the site settings icon in your browser\'s address bar and grant microphone permission, then try again.');
            } else {
                alert('Could not start streaming: ' + e.message);
            }
        }
    }

    async function handleStartStreamingMp3(jobId: string) {
        if (!streamMp3File) {
            return;
        }
        try {
            await service.startJob(jobId);
            const elAudio = new Audio();
            elAudio.src = URL.createObjectURL(streamMp3File);
            const context = new AudioContext();
            if (context.state === 'suspended') {
                await context.resume();
            }
            const source = context.createMediaElementSource(elAudio);
            elAudio.addEventListener('ended', () => stopStreaming());
            startAudioPipeline(jobId, context, source, {audioEl: elAudio, label: 'mp3'});
            elAudio.play();
        } catch (e: any) {
            alert('Could not play MP3: ' + e.message);
        }
    }

    function stopStreaming() {
        if (!audioState.active) {
            return;
        }
        if (audioState.buf!.samples.length > 0) {
            sendAudioChunk(audioState.jobId!, audioState.buf!.samples, audioState.nativeSampleRate!);
        }
        audioState.processor!.disconnect();
        audioState.audioSource!.disconnect();
        audioState.context!.close();
        if (audioState.stream) {
            audioState.stream.getTracks().forEach(t => t.stop());
        }
        if (audioState.audioEl) {
            audioState.audioEl.pause();
            URL.revokeObjectURL(audioState.audioEl.src);
        }
        if (audioState.vizFrame) {
            cancelAnimationFrame(audioState.vizFrame);
        }
        clearInterval(audioState.timer!);
        service.stopAudio(audioState.jobId!);
        audioState = {jobId: null, active: false, paused: false, context: null, processor: null, timer: null, seconds: 0};
        callbacks.onRender();
    }

    function pauseAudio() {
        if (!audioState.active || audioState.paused) {
            return;
        }
        audioState.paused = true;
        if (audioState.timer) {
            clearInterval(audioState.timer);
            audioState.timer = null;
        }
        if (audioState.vizFrame) {
            cancelAnimationFrame(audioState.vizFrame);
            audioState.vizFrame = null;
        }
        if (audioState.audioEl) {
            audioState.audioEl.pause();
        }
        callbacks.onRender();
    }

    function resumeAudio() {
        if (!audioState.active || !audioState.paused) {
            return;
        }
        audioState.paused = false;
        audioState.timer = setInterval(() => {
            audioState.seconds++;
            callbacks.onRecordingTick(audioState.seconds);
        }, 1000);
        if (audioState.audioEl) {
            audioState.audioEl.play();
        }
        startVisualizer();
        callbacks.onRender();
    }

    function selectStreamMp3(file: File) {
        streamMp3File = file;
    }

    function getAudioInfo(): AudioInfo {
        return {
            active: audioState.active,
            paused: audioState.paused,
            jobId: audioState.jobId,
            label: audioState.label,
            seconds: audioState.seconds,
        };
    }

    function getStreamMp3Name(): string | null {
        return streamMp3File ? streamMp3File.name : null;
    }

    return {
        handleStartStreaming,
        handleStartStreamingMp3,
        stopStreaming,
        pauseAudio,
        resumeAudio,
        selectStreamMp3,
        getAudioInfo,
        getStreamMp3Name,
    };
}
