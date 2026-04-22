// ── Transcript View ──

import {buildEmitter} from '../events';
import {escHtml, escAttr, formatTime, tmpl, makeEl, determineVerdict, strHash, reconcileKeyed, ReconcileItem} from './utils';
import {TranscriptView, TranscriptData, AudioInfo, Annotation, FactCheck, AnalysisResult, Utterance} from '../types';

export function buildTranscriptView(): TranscriptView {
    const {on, emit} = buildEmitter(),
        elCol = document.getElementById('transcriptCol');
    let annotationCounter = 0,
        userScrolledUp = false;

    function renderStatusBar(status: string, audio: AudioInfo, jobId: string, isStreaming: boolean, rateLimited: boolean): HTMLElement | null {
        const isRunning = status === 'ingesting' || status === 'analysing' || status === 'reviewing',
            audioPaused = audio && audio.active && audio.paused,
            elBar = tmpl('tmpl-status-bar'),
            elDot = elBar.querySelector('.status-bar-dot') as HTMLElement,
            elLabel = elBar.querySelector('.status-bar-label') as HTMLElement,
            elAudio = elBar.querySelector('.status-bar-audio') as HTMLElement,
            elStartBtn = elBar.querySelector('[data-action="start-job"]') as HTMLElement,
            elPauseBtn = elBar.querySelector('[data-action="pause-job"]') as HTMLElement,
            elAbortBtn = elBar.querySelector('[data-action="abort-job"]') as HTMLElement;

        if (status === 'init') {
            elDot.className = 'status-bar-dot init';
            elLabel.textContent = 'Ready';
            elBar.classList.add('init');
            elStartBtn.hidden = false;
            elStartBtn.dataset.jobId = jobId;
        } else if (isRunning) {
            elDot.className = 'status-bar-dot ' + status;
            elLabel.textContent = status === 'ingesting' ? 'Live' : status === 'analysing' ? 'Analysing' : 'Reviewing';
            elBar.classList.add('live');
            if (isStreaming && status === 'ingesting') {
                elAbortBtn.dataset.action = 'stop-streaming';
                elAbortBtn.hidden = false;
                if (audio && audio.active && audio.jobId === jobId) {
                    if (audioPaused) {
                        elPauseBtn.textContent = 'Resume';
                        elPauseBtn.dataset.action = 'resume-audio';
                    }
                    elPauseBtn.hidden = false;
                }
            } else {
                elAbortBtn.hidden = false;
            }
        } else if (status === 'complete') {
            elDot.className = 'status-bar-dot complete';
            elLabel.textContent = 'Complete';
            elBar.classList.add('complete');
        } else if (status === 'aborted') {
            elDot.className = 'status-bar-dot aborted';
            elLabel.textContent = 'Aborted';
            elBar.classList.add('aborted');
        } else {
            return null;
        }

        if (audio && audio.active && audio.jobId === jobId && !audioPaused) {
            elAudio.hidden = false;
            const label = audio.label === 'mp3' ? 'Playing MP3' : 'Recording';
            elAudio.querySelector('.rec-label')!.textContent = label + '\u2002';
            elBar.querySelector('#recTime')!.textContent = formatTime(audio.seconds);
        }

        if (rateLimited && isRunning) {
            const elThrottle = makeEl('span', 'status-bar-throttle', 'Rate limited — waiting to retry');
            elLabel.after(elThrottle);
        }

        return elBar;
    }

    const verdictSeverity: Record<string, number> = {
        'no-fc': 0,
        'established': 1,
        'pending': 2,
        'unsupported': 3,
        'misleading': 4,
        'false': 5,
    };

    function worstVerdict(annotations: Annotation[], factChecks: Record<string, FactCheck>): string {
        return annotations.reduce((worst, ann) => {
            const v = determineVerdict(ann, factChecks);
            return (verdictSeverity[v] ?? 0) > (verdictSeverity[worst] ?? 0) ? v : worst;
        }, 'no-fc');
    }

    interface Segment {
        key?: string;   // stable id (utterance_id) for reusable paragraphs
        hash?: string;  // content signature; same hash on same key -> reuse
        html: string;   // outer HTML for the segment
    }

    function buildSegments(utterances: Utterance[], analysis: Record<string, AnalysisResult>, factChecks: Record<string, FactCheck>, isRunning: boolean): Segment[] {
        annotationCounter = 0;
        const segments: Segment[] = [];
        let rawTexts: string[] = [],
            lastRemainder = '';

        const flushRaw = () => {
            if (rawTexts.length > 0) {
                segments.push({html: `<p class="transcript-raw">${escHtml(rawTexts.join(' '))}</p>`});
                rawTexts = [];
            }
        };

        utterances.forEach(utt => {
            const anal = analysis[utt.utterance_id];

            if (anal && anal.parts && anal.parts.length > 0 && !anal.failed) {
                flushRaw();
                let inner = '';
                anal.parts.forEach(part => {
                    let text = escHtml(part.corrected_text);
                    if (part.annotations && part.annotations.length > 0) {
                        part.annotations.forEach(ann => {
                            annotationCounter++;
                            ann._refNum = annotationCounter;
                        });
                        const primaryAnn = part.annotations[0],
                            type = primaryAnn.type || 'CLAIM',
                            allRefs = part.annotations.map(a => a._refNum).join(','),
                            allAnnIds = part.annotations.map(a => a.annotation_id).join(','),
                            verdict = worstVerdict(part.annotations, factChecks);
                        text = `<span class="anno-mark ${escAttr(type)}" data-ref="${primaryAnn._refNum}" data-all-refs="${allRefs}" data-annotation-ids="${escAttr(allAnnIds)}" data-type="${escAttr(type)}" data-verdict="${verdict}">`
                            + text
                            + `</span>`;
                        part.annotations.forEach(ann => {
                            const annType = ann.type || 'CLAIM';
                            text += `<sup class="anno-ref" data-ref="${ann._refNum}" data-type="${escAttr(annType)}">${ann._refNum}</sup>`;
                        });
                    }
                    inner += text + ' ';
                });
                inner = inner.trim();
                const hash = strHash(inner);
                segments.push({
                    key: utt.utterance_id,
                    hash,
                    html: `<p data-utterance-id="${escAttr(utt.utterance_id)}" data-hash="${hash}">${inner}</p>`,
                });
                lastRemainder = anal.remainder || '';
            } else if (anal && anal.failed) {
                flushRaw();
                segments.push({html: `<div class="analysis-error">Analysis failed for this utterance</div>`});
                lastRemainder = '';
            } else {
                if (lastRemainder && rawTexts.length === 0) {
                    rawTexts.push(lastRemainder);
                }
                rawTexts.push(utt.text);
            }
        });

        if (rawTexts.length > 0) {
            const cursor = isRunning ? `<span class="live-cursor"></span>` : '';
            segments.push({html: `<p class="transcript-raw">${escHtml(rawTexts.join(' '))}${cursor}</p>`});
        }

        return segments;
    }

    function buildElement(html: string): HTMLElement {
        const tmp = document.createElement('template');
        tmp.innerHTML = html;
        return tmp.content.firstElementChild as HTMLElement;
    }

    function render(data: TranscriptData | null): void {
        if (!elCol) {
            return;
        }

        if (!data) {
            elCol.innerHTML = '<div class="empty-state">Select or create a transcript to begin</div>';
            userScrolledUp = false;
            return;
        }

        const {utterances, analysis, factChecks, status, context, jobId, audio, isStreaming, rateLimited} = data,
            isRunning = status === 'ingesting' || status === 'analysing' || status === 'reviewing',
            wasAtBottom = isRunning && !userScrolledUp;

        // Rebuild the status bar each render (small, no hover concerns).
        const existingBar = elCol.querySelector(':scope > .status-bar');
        if (existingBar) existingBar.remove();
        const existingEmpty = elCol.querySelector(':scope > .empty-state');
        if (existingEmpty) existingEmpty.remove();

        const elBar = renderStatusBar(status, audio, jobId, isStreaming, rateLimited);
        if (elBar) {
            elCol.insertBefore(elBar, elCol.firstChild);
        }

        let elDiv = elCol.querySelector(':scope > .transcript-text') as HTMLElement | null;

        if (utterances.length === 0) {
            if (elDiv) {
                elDiv.remove();
                elDiv = null;
            }
            const msg = isRunning ? 'Waiting for data...'
                : (status !== 'init' ? 'No transcript data' : null);
            if (msg) {
                elCol.appendChild(makeEl('div', 'empty-state', msg));
            }
        } else {
            if (!elDiv) {
                elDiv = makeEl('div', 'transcript-text');
                elCol.appendChild(elDiv);
            }
            const segments = buildSegments(utterances, analysis, factChecks || {}, isRunning);
            const items: ReconcileItem[] = segments.map(seg => ({
                key: seg.key,
                hash: seg.hash,
                build: () => buildElement(seg.html),
            }));
            reconcileKeyed(elDiv, items, 'utteranceId');
        }

        if (wasAtBottom) {
            elCol.scrollTop = elCol.scrollHeight;
        }
    }

    function updateRecordingTime(seconds: number): void {
        const elTime = document.getElementById('recTime');
        if (elTime) {
            elTime.textContent = formatTime(seconds);
        }
    }

    function updateVisualizer(dataArray: Uint8Array, barCount: number): void {
        const elContainer = document.getElementById('audioViz');
        if (!elContainer) {
            return;
        }
        while (elContainer.children.length < barCount) {
            const elBar = document.createElement('div');
            elBar.className = 'viz-bar';
            elContainer.appendChild(elBar);
        }
        const binStep = dataArray.length / barCount;
        for (let i = 0; i < barCount; i++) {
            const binIndex = Math.floor(i * binStep),
                value = dataArray[binIndex] / 255;
            (elContainer.children[i] as HTMLElement).style.height = Math.max(2, value * 20) + 'px';
        }
    }

    elCol!.addEventListener('click', (e: MouseEvent) => {
        const elStartBtn = (e.target as HTMLElement).closest('[data-action="start-job"]') as HTMLElement | null;
        if (elStartBtn) {
            emit('startJob', elStartBtn.dataset.jobId);
            return;
        }
        if ((e.target as HTMLElement).closest('[data-action="pause-job"]')) {
            emit('pauseAudio');
            return;
        }
        if ((e.target as HTMLElement).closest('[data-action="resume-audio"]')) {
            emit('resumeAudio');
            return;
        }
        if ((e.target as HTMLElement).closest('[data-action="stop-streaming"]')) {
            emit('stopStreaming');
            return;
        }
        if ((e.target as HTMLElement).closest('[data-action="abort-job"]')) {
            emit('abortJob');
            return;
        }
    });

    elCol!.addEventListener('scroll', function (this: HTMLElement) {
        userScrolledUp = (this.scrollTop + this.clientHeight) < (this.scrollHeight - 50);
    });

    function showMicrophonePrompt(): void {
        const elLabel = document.querySelector('.status-bar-label');
        const elStartBtn = document.querySelector('[data-action="start-job"]') as HTMLElement | null;
        if (elLabel) {
            elLabel.textContent = 'Waiting for microphone...';
        }
        if (elStartBtn) {
            elStartBtn.hidden = true;
        }
    }

    return {on, render, updateRecordingTime, updateVisualizer, showMicrophonePrompt};
}
