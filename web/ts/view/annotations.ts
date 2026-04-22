// ── Annotation View ──
// Manages the interactive linking between transcript marks and margin notes.
// Selection state lives in the store; this module translates DOM events
// into store mutations, and renders the store's selection state to DOM
// classes via applySelection().
//
// Listeners are attached once at construction time via event delegation
// on elTranscriptCol and elMarginCol — per-element wiring is unnecessary.
//
// On desktop: highlights margin notes in the right column.
// On mobile: inserts margin notes inline below the tapped paragraph.

import {AnnotationView, JobStore} from '../types';

const mobileQuery = window.matchMedia('(max-width: 1100px)');

interface MarkEntry {
    elMark: HTMLElement;
    elNotes: HTMLElement[];
}

export function buildAnnotationView(
    elTranscriptCol: HTMLElement,
    elMarginCol: HTMLElement,
    store: JobStore,
): AnnotationView {
    // Indices rebuilt each setup() from the current DOM. Used by event
    // handlers and applySelection() to look up marks/notes by ref / ann id.
    let refToMark: Record<string, MarkEntry> = {};
    let annIdToMark: Record<string, HTMLElement> = {};

    // Mobile-only: the dynamically-inserted inline-notes block below the
    // selected paragraph. Lifecycle is driven by applySelection().
    let elInline: HTMLElement | null = null;

    function isMobile(): boolean {
        return mobileQuery.matches;
    }

    function updateHash(ref: string | null, push: boolean): void {
        const jobId = location.hash.slice(1).split('/')[0];
        if (!jobId) {
            return;
        }
        const newHash = ref ? '#' + jobId + '/' + ref : '#' + jobId;
        if (push) {
            history.pushState(null, '', newHash);
        } else {
            history.replaceState(null, '', newHash);
        }
    }

    function findingCardMatches(elCard: HTMLElement, refs: string[] | null): boolean {
        if (!refs) return false;
        const cardRefs = (elCard.dataset.refs || '').split(',').filter(Boolean);
        if (cardRefs.length !== refs.length) return false;
        return cardRefs.every((r, i) => r === refs[i]);
    }

    // Mirror the store's selection state onto the DOM. Idempotent; safe to
    // call repeatedly. Called on every store 'selectionChanged' event and
    // after setup() (elements may have been rebuilt by reconciliation).
    function applySelection(): void {
        elTranscriptCol.querySelectorAll('.anno-mark.active')
            .forEach(el => el.classList.remove('active'));
        elMarginCol.querySelectorAll('.margin-note.highlighted')
            .forEach(el => el.classList.remove('highlighted'));
        elMarginCol.querySelectorAll('.review-finding.active')
            .forEach(el => el.classList.remove('active'));

        const selectedRef = store.getSelectedRef();
        const activeFindingRefs = store.getActiveFindingRefs();

        if (selectedRef) {
            const entry = refToMark[selectedRef];
            if (entry) {
                entry.elMark.classList.add('active');
                if (isMobile()) {
                    // Mobile: mirror the margin notes inline below the paragraph.
                    // Rebuild if the ref changed or the source notes' hashes
                    // changed (their content was reconciled to a new version).
                    const sourceHash = entry.elNotes.map(n => n.dataset.hash || '').join('|');
                    if (elInline && (elInline.dataset.ref !== selectedRef
                            || elInline.dataset.sourceHash !== sourceHash)) {
                        elInline.remove();
                        elInline = null;
                    }
                    if (!elInline && entry.elNotes.length > 0) {
                        const elParagraph = entry.elMark.closest('p');
                        if (elParagraph) {
                            elInline = document.createElement('div');
                            elInline.className = 'inline-notes';
                            elInline.dataset.ref = selectedRef;
                            elInline.dataset.sourceHash = sourceHash;
                            entry.elNotes.forEach(n => {
                                const elClone = n.cloneNode(true) as HTMLElement;
                                elClone.classList.add('highlighted');
                                elInline!.appendChild(elClone);
                            });
                            elParagraph.after(elInline);
                        }
                    }
                } else {
                    entry.elNotes.forEach(n => n.classList.add('highlighted'));
                    if (elInline) {
                        elInline.remove();
                        elInline = null;
                    }
                }
            }
        } else {
            if (elInline) {
                elInline.remove();
                elInline = null;
            }
        }
        if (!selectedRef && activeFindingRefs) {
            elMarginCol.querySelectorAll('.review-finding').forEach(el => {
                if (findingCardMatches(el as HTMLElement, activeFindingRefs)) {
                    el.classList.add('active');
                }
            });
            activeFindingRefs.forEach(annId => {
                const elMark = annIdToMark[annId];
                if (elMark) elMark.classList.add('active');
            });
        }
    }

    // ── Actions (translate user intent into store mutations + side effects) ──

    function onRefClicked(ref: string): void {
        if (store.getSelectedRef() === ref) {
            updateHash(null, true);
            store.clearSelection();
            return;
        }
        updateHash(ref, true);
        store.setSelection(ref);
        const entry = refToMark[ref];
        if (!entry) return;
        if (isMobile()) {
            const elParagraph = entry.elMark.closest('p');
            if (elParagraph) elParagraph.scrollIntoView({behavior: 'smooth', block: 'start'});
        } else if (entry.elNotes.length > 0) {
            entry.elNotes[0].scrollIntoView({behavior: 'smooth', block: 'start'});
        }
    }

    function onFindingClicked(elCard: HTMLElement): void {
        const refs = (elCard.dataset.refs || '').split(',').filter(Boolean);
        if (refs.length === 0) return;
        if (findingCardMatches(elCard, store.getActiveFindingRefs())) {
            store.clearSelection();
            return;
        }
        store.setActiveFinding(refs);
        const firstEl = annIdToMark[refs[0]];
        if (firstEl) firstEl.scrollIntoView({behavior: 'smooth', block: 'center'});
    }

    // ── Event delegation: transcript column ──

    elTranscriptCol.addEventListener('click', (e: MouseEvent) => {
        const target = e.target as HTMLElement;
        const elRef = target.closest('.anno-ref[data-ref]') as HTMLElement | null;
        if (elRef) {
            e.stopPropagation();
            onRefClicked(elRef.dataset.ref!);
            return;
        }
        const elMark = target.closest('.anno-mark') as HTMLElement | null;
        if (elMark && elMark.dataset.ref) {
            onRefClicked(elMark.dataset.ref);
        }
    });

    // Hover handling on anno-marks. mouseenter/mouseleave don't bubble, so
    // we use mouseover/mouseout and discard transitions between descendants
    // of the same mark via a relatedTarget.contains() check.
    elTranscriptCol.addEventListener('mouseover', (e: MouseEvent) => {
        if (store.getSelectedRef() || store.getActiveFindingRefs()) return;
        const elMark = (e.target as HTMLElement).closest('.anno-mark') as HTMLElement | null;
        if (!elMark) return;
        const from = e.relatedTarget as HTMLElement | null;
        if (from && elMark.contains(from)) return;
        const ref = elMark.dataset.ref;
        if (!ref) return;
        const entry = refToMark[ref];
        if (entry) entry.elNotes.forEach(n => n.classList.add('highlighted'));
    });

    elTranscriptCol.addEventListener('mouseout', (e: MouseEvent) => {
        if (store.getSelectedRef() || store.getActiveFindingRefs()) return;
        const elMark = (e.target as HTMLElement).closest('.anno-mark') as HTMLElement | null;
        if (!elMark) return;
        const to = e.relatedTarget as HTMLElement | null;
        if (to && elMark.contains(to)) return;
        const ref = elMark.dataset.ref;
        if (!ref) return;
        const entry = refToMark[ref];
        if (entry) entry.elNotes.forEach(n => n.classList.remove('highlighted'));
    });

    // ── Event delegation: margin column ──

    elMarginCol.addEventListener('click', (e: MouseEvent) => {
        const target = e.target as HTMLElement;
        const elCard = target.closest('.review-finding') as HTMLElement | null;
        if (elCard) {
            onFindingClicked(elCard);
            return;
        }
        if (target.closest('.margin-citations')) return;
        const elNote = target.closest('.margin-note') as HTMLElement | null;
        if (elNote && elNote.dataset.ref) {
            const ref = elNote.dataset.ref;
            onRefClicked(ref);
            const entry = refToMark[ref];
            if (entry) entry.elMark.scrollIntoView({behavior: 'smooth', block: 'center'});
        }
    });

    // Document-level click — clears selection when clicking outside the
    // interactive regions. Must not fire when clicking inside columns since
    // those have their own handlers above.
    document.addEventListener('click', (e: MouseEvent) => {
        const target = e.target as HTMLElement;
        if (target.closest('.anno-mark') ||
            target.closest('.anno-ref') ||
            target.closest('.margin-note') ||
            target.closest('.inline-notes') ||
            target.closest('.review-finding')) {
            return;
        }
        if (store.getSelectedRef() || store.getActiveFindingRefs()) {
            updateHash(null, true);
            store.clearSelection();
        }
    });

    store.on('selectionChanged', applySelection);

    // ── External entry points ──

    function selectRef(ref: string | null): void {
        // Called on browser back/forward (popstate) within the same job.
        // The URL is already set by the browser, so we don't touch history.
        if (!ref) {
            if (store.getSelectedRef() || store.getActiveFindingRefs()) {
                store.clearSelection();
            }
            return;
        }
        if (!refToMark[ref]) return;
        if (store.getSelectedRef() === ref) return;
        store.setSelection(ref);
        refToMark[ref].elMark.scrollIntoView({behavior: 'smooth', block: 'center'});
    }

    function setup(): void {
        // Rebuild ref/annId indices from the current DOM. These are the only
        // per-render work this module does now — event listeners are attached
        // once at construction via delegation.
        refToMark = {};
        annIdToMark = {};

        elTranscriptCol.querySelectorAll('.anno-mark').forEach(el => {
            const elMark = el as HTMLElement,
                allRefs = (elMark.dataset.allRefs || elMark.dataset.ref || '').split(','),
                allAnnIds = (elMark.dataset.annotationIds || '').split(',').filter(Boolean),
                elNotes = allRefs.map(r => document.getElementById('note-' + r))
                    .filter(Boolean) as HTMLElement[];
            if (elNotes.length === 0) return;
            allRefs.forEach(r => { refToMark[r] = {elMark, elNotes}; });
            allAnnIds.forEach(id => { annIdToMark[id] = elMark; });
        });

        // On first setup after a navigation, restore selection from URL hash.
        const hashRef = location.hash.slice(1).split('/')[1];
        if (hashRef && refToMark[hashRef] && store.getSelectedRef() !== hashRef) {
            store.setSelection(hashRef);  // triggers applySelection via event
            refToMark[hashRef].elMark.scrollIntoView({behavior: 'instant', block: 'center'});
            return;
        }

        // Re-apply selection classes; elements may have been rebuilt by
        // reconciliation during render, so existing classes may have been lost.
        applySelection();
    }

    return {setup, selectRef};
}
