// ── Annotation View ──
// Manages the interactive linking between transcript marks and margin notes.
// On desktop: highlights margin notes in the right column.
// On mobile: inserts margin notes inline below the tapped paragraph.

import {AnnotationView} from '../types';

const mobileQuery = window.matchMedia('(max-width: 1100px)');

interface MarkEntry {
    elMark: HTMLElement;
    elNotes: HTMLElement[];
}

export function buildAnnotationView(elTranscriptCol: HTMLElement): AnnotationView {

    // Selection state — avoids DOM queries on every hover/click
    let sel: {elMark: HTMLElement | null; elNotes: HTMLElement[]; elInline: HTMLElement | null} = {elMark: null, elNotes: [], elInline: null};

    function isMobile(): boolean {
        return mobileQuery.matches;
    }

    function updateHash(ref: string | null, push: boolean = false): void {
        const parts = location.hash.slice(1).split('/'),
            jobId = parts[0];
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

    function select(elMark: HTMLElement, elNotes: HTMLElement[], push: boolean = true, scroll: boolean = true): void {
        clearSelection();
        clearFindingHighlight();
        sel = {elMark, elNotes, elInline: null};
        elMark.classList.add('active');

        updateHash(elMark.dataset.ref || null, push);

        if (isMobile()) {
            // Insert cloned notes inline below the paragraph containing the mark
            const elParagraph = elMark.closest('p');
            if (elParagraph && elNotes.length > 0) {
                const elInline = document.createElement('div');
                elInline.className = 'inline-notes';
                elNotes.forEach(n => {
                    const elClone = n.cloneNode(true) as HTMLElement;
                    elClone.classList.add('highlighted');
                    elInline.appendChild(elClone);
                });
                elParagraph.after(elInline);
                sel.elInline = elInline;
                if (scroll) {
                    elInline.scrollIntoView({behavior: 'smooth', block: 'nearest'});
                }
            }
        } else {
            elNotes.forEach(n => n.classList.add('highlighted'));
            if (scroll) {
                elNotes[0].scrollIntoView({behavior: 'smooth', block: 'start'});
            }
        }
    }

    function clearSelection(): void {
        if (sel.elMark) {
            sel.elMark.classList.remove('active');
        }
        sel.elNotes.forEach(n => n.classList.remove('highlighted'));
        if (sel.elInline) {
            sel.elInline.remove();
        }
        sel = {elMark: null, elNotes: [], elInline: null};
    }

    function deselect(): void {
        if (sel.elMark) {
            updateHash(null, true);
        }
        clearSelection();
    }

    let refToMark: Record<string, MarkEntry> = {},
        annIdToMark: Record<string, HTMLElement> = {},
        activeFinding: HTMLElement | null = null,
        highlightedMarks: HTMLElement[] = [];

    function clearFindingHighlight(): void {
        if (activeFinding) {
            activeFinding.classList.remove('active');
            activeFinding = null;
        }
        highlightedMarks.forEach(m => m.classList.remove('active'));
        highlightedMarks = [];
    }

    function highlightFinding(elCard: HTMLElement): void {
        clearSelection();
        clearFindingHighlight();
        const refs = (elCard.dataset.refs || '').split(',').filter(Boolean);
        activeFinding = elCard;
        elCard.classList.add('active');
        for (const annId of refs) {
            const elMark = annIdToMark[annId];
            if (elMark) {
                elMark.classList.add('active');
                highlightedMarks.push(elMark);
            }
        }
        if (highlightedMarks.length > 0) {
            highlightedMarks[0].scrollIntoView({behavior: 'smooth', block: 'center'});
        }
    }

    function selectRef(ref: string | null): void {
        if (!ref) {
            deselect();
            return;
        }
        const entry = refToMark[ref];
        if (entry) {
            select(entry.elMark, entry.elNotes, false);
            entry.elMark.scrollIntoView({behavior: 'smooth', block: 'center'});
        }
    }

    function setup(): void {
        refToMark = {};
        annIdToMark = {};

        document.querySelectorAll('.anno-mark').forEach(el => {
            const elMark = el as HTMLElement,
                allRefs = (elMark.dataset.allRefs || elMark.dataset.ref || '').split(','),
                allAnnIds = (elMark.dataset.annotationIds || '').split(',').filter(Boolean),
                elNotes = allRefs.map(r => document.getElementById('note-' + r)).filter(Boolean) as HTMLElement[];
            if (elNotes.length === 0) {
                return;
            }

            allRefs.forEach(r => { refToMark[r] = {elMark, elNotes}; });
            allAnnIds.forEach(id => { annIdToMark[id] = elMark; });

            elMark.addEventListener('mouseenter', () => {
                if (!sel.elMark) {
                    elNotes.forEach(n => n.classList.add('highlighted'));
                }
            });
            elMark.addEventListener('mouseleave', () => {
                if (!sel.elMark) {
                    elNotes.forEach(n => n.classList.remove('highlighted'));
                }
            });

            elMark.addEventListener('click', (e: MouseEvent) => {
                if ((e.target as HTMLElement).closest('.anno-ref')) {
                    return;
                }
                if (sel.elMark === elMark) {
                    deselect();
                    return;
                }
                select(elMark, elNotes);
            });
        });

        document.querySelectorAll('.anno-ref[data-ref]').forEach(el => {
            const elSup = el as HTMLElement;
            elSup.addEventListener('click', (e: MouseEvent) => {
                e.stopPropagation();
                const entry = refToMark[elSup.dataset.ref!];
                if (!entry) {
                    return;
                }
                if (sel.elMark === entry.elMark) {
                    deselect();
                    return;
                }
                select(entry.elMark, entry.elNotes);
            });
        });

        document.querySelectorAll('.margin-note').forEach(el => {
            const elNote = el as HTMLElement,
                entry = refToMark[elNote.dataset.ref!];
            if (!entry) {
                return;
            }

            elNote.addEventListener('click', (e: MouseEvent) => {
                if ((e.target as HTMLElement).closest('.margin-citations')) {
                    return;
                }
                if (sel.elMark === entry.elMark) {
                    deselect();
                    return;
                }
                select(entry.elMark, entry.elNotes);
                entry.elMark.scrollIntoView({behavior: 'smooth', block: 'center'});
            });
        });

        // Review finding click handlers
        document.querySelectorAll('.review-finding').forEach(el => {
            const elCard = el as HTMLElement;
            elCard.addEventListener('click', () => {
                if (activeFinding === elCard) {
                    clearFindingHighlight();
                    return;
                }
                highlightFinding(elCard);
            });
        });

        // Restore selection from URL hash (e.g. #jobId/3).
        // setup() runs on every render; only scroll the first time we
        // restore this ref, otherwise the page jumps each time data arrives.
        const hashRef = location.hash.slice(1).split('/')[1];
        if (hashRef) {
            const entry = refToMark[hashRef];
            if (entry) {
                const alreadySelected = sel.elMark?.dataset?.ref === hashRef;
                select(entry.elMark, entry.elNotes, false, !alreadySelected);
                if (!alreadySelected) {
                    entry.elMark.scrollIntoView({behavior: 'instant', block: 'center'});
                }
            }
        }
    }

    document.addEventListener('click', (e: MouseEvent) => {
        if ((e.target as HTMLElement).closest('.review-finding')) {
            return;
        }
        if (!(e.target as HTMLElement).closest('.anno-mark') && !(e.target as HTMLElement).closest('.margin-note') && !(e.target as HTMLElement).closest('.inline-notes')) {
            clearFindingHighlight();
            deselect();
        }
    });

    return {setup, selectRef};
}
