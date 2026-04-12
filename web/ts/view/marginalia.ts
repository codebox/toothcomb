// ── Marginalia View ──

import {tmpl, makeEl, determineVerdict} from './utils';
import {MarginaliaView, MarginaliaData, Annotation, FactCheck, ReviewFinding} from '../types';

export function buildMarginaliaView(): MarginaliaView {
    const elCol = document.getElementById('marginCol');
    let userScrolledUp = false;

    if (elCol) {
        elCol.addEventListener('scroll', function (this: HTMLElement) {
            userScrolledUp = (this.scrollTop + this.clientHeight) < (this.scrollHeight - 50);
        });
    }

    function buildMarginNote(ann: Annotation, refNum: number, factChecks: Record<string, FactCheck>): HTMLElement {
        const elNote = tmpl('tmpl-margin-note'),
            type = ann.type || 'CLAIM',
            fc = factChecks[ann.annotation_id];

        elNote.id = 'note-' + refNum;
        elNote.dataset.type = type;
        elNote.dataset.ref = String(refNum);
        elNote.querySelector('.margin-ref')!.textContent = String(refNum);

        const ledClass = determineVerdict(ann, factChecks);
        elNote.dataset.verdict = ledClass;
        elNote.querySelector('.margin-led')!.className = 'margin-led ' + ledClass;
        elNote.querySelector('.margin-type')!.textContent = type;
        elNote.querySelector('.margin-notes')!.textContent = ann.notes;

        if (fc) {
            const elVerdict = elNote.querySelector('.margin-verdict') as HTMLElement,
                elLabel = elVerdict.querySelector('.margin-verdict-label') as HTMLElement;
            elVerdict.hidden = false;
            elLabel.textContent = fc.verdict + ':';
            elLabel.classList.add(fc.verdict.toLowerCase());
            elVerdict.querySelector('.margin-verdict-text')!.textContent = fc.note;
            if (fc.citations && fc.citations.length > 0) {
                const elDetails = document.createElement('details');
                elDetails.className = 'margin-citations';
                const elSummary = document.createElement('summary');
                elSummary.textContent = fc.citations.length === 1 ? '1 source' : fc.citations.length + ' sources';
                elDetails.appendChild(elSummary);
                const elList = document.createElement('ol');
                fc.citations.forEach(c => {
                    const elItem = document.createElement('li');
                    const elLink = document.createElement('a');
                    elLink.href = c.url;
                    elLink.textContent = c.title || c.url;
                    elLink.target = '_blank';
                    elLink.rel = 'noopener noreferrer';
                    elItem.appendChild(elLink);
                    elList.appendChild(elItem);
                });
                elDetails.appendChild(elList);
                elVerdict.appendChild(elDetails);
            }
        } else if (ann.fact_check_query) {
            (elNote.querySelector('.margin-pending') as HTMLElement).hidden = false;
        }

        return elNote;
    }

    function buildFindingCard(finding: ReviewFinding): HTMLElement {
        const elCard = document.createElement('div');
        elCard.className = 'review-finding';
        elCard.dataset.refs = finding.refs.join(',');

        const elHeader = makeEl('div', 'review-finding-header');
        elHeader.appendChild(makeEl('span', 'review-finding-technique', finding.technique));
        elHeader.appendChild(makeEl('span', 'margin-type', finding.type));
        elCard.appendChild(elHeader);

        elCard.appendChild(makeEl('div', 'review-finding-summary', finding.summary));

        if (finding.excerpt) {
            elCard.appendChild(makeEl('div', 'review-finding-excerpt', finding.excerpt));
        }

        if (finding.refs.length > 0) {
            const elRefs = makeEl('div', 'review-finding-refs');
            elRefs.textContent = finding.refs.length === 1 ? '1 related annotation' : finding.refs.length + ' related annotations';
            elCard.appendChild(elRefs);
        }

        return elCard;
    }

    function render(data: MarginaliaData | null): void {
        if (!elCol) {
            return;
        }
        elCol.innerHTML = '';
        if (!data) {
            userScrolledUp = false;
            return;
        }

        const {utterances, analysis, factChecks, review} = data;
        let refNum = 0;

        utterances.forEach(utt => {
            const analysisItem = analysis[utt.utterance_id];
            if (!analysisItem || !analysisItem.parts || analysisItem.failed) {
                return;
            }

            analysisItem.parts.forEach(part => {
                if (!part.annotations || part.annotations.length === 0) {
                    return;
                }
                part.annotations.forEach(ann => {
                    refNum++;
                    elCol.appendChild(buildMarginNote(ann, refNum, factChecks));
                });
            });
        });

        if (review && review.findings && review.findings.length > 0) {
            elCol.appendChild(makeEl('div', 'review-findings-label', 'Review Findings'));
            review.findings.forEach(finding => {
                elCol.appendChild(buildFindingCard(finding));
            });
        }

        const isRunning = data.status === 'ingesting' || data.status === 'analysing' || data.status === 'reviewing',
            hasSelection = elCol.querySelector('.margin-note.highlighted, .review-finding.active') !== null;
        if (isRunning && !hasSelection && !userScrolledUp) {
            elCol.scrollTop = elCol.scrollHeight;
        }
    }

    return {render};
}
