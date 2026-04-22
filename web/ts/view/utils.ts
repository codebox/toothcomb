// ── View Utilities ──

export function escHtml(s: any): string {
    if (!s) {
        return '';
    }
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function escAttr(s: any): string {
    return escHtml(s);
}

export function formatTime(totalSeconds: number): string {
    const m = Math.floor(totalSeconds / 60).toString().padStart(2, '0'),
        s = (totalSeconds % 60).toString().padStart(2, '0');
    return m + ':' + s;
}

// Clone a <template> element's first child as a new DOM node.
export function tmpl(id: string): HTMLElement {
    return (document.getElementById(id) as HTMLTemplateElement).content.firstElementChild!.cloneNode(true) as HTMLElement;
}

export function makeEl(tag: string, className?: string, text?: string): HTMLElement {
    const el = document.createElement(tag);
    if (className) {
        el.className = className;
    }
    if (text !== undefined) {
        el.textContent = text;
    }
    return el;
}

// Wire a drop zone with click-to-browse, dragover/dragleave/drop, and file selection.
export function wireDropZone(elZone: HTMLElement, elInput: HTMLInputElement, onFile: (file: File) => void): void {
    elZone.addEventListener('click', () => elInput.click());
    elInput.addEventListener('change', () => {
        if (elInput.files && elInput.files.length > 0) {
            onFile(elInput.files[0]);
        }
    });
    elZone.addEventListener('dragover', (e: DragEvent) => {
        e.preventDefault();
        elZone.classList.add('dragover');
    });
    elZone.addEventListener('dragleave', () => elZone.classList.remove('dragover'));
    elZone.addEventListener('drop', (e: DragEvent) => {
        e.preventDefault();
        elZone.classList.remove('dragover');
        if (e.dataTransfer && e.dataTransfer.files.length > 0) {
            elInput.files = e.dataTransfer.files;
            onFile(e.dataTransfer.files[0]);
        }
    });
}

import {Annotation, FactCheck} from '../types';

export function determineVerdict(ann: Annotation, factChecks: Record<string, FactCheck>): string {
    const fc = factChecks[ann.annotation_id];
    if (fc) {
        return fc.verdict.toLowerCase();
    }
    return ann.fact_check_query ? 'pending' : 'no-fc';
}

// djb2 string hash — short base36 signature used by render reconciliation to
// detect content changes. Collisions are possible but rare enough to ignore:
// the worst case is a stale paragraph shown for one render cycle.
export function strHash(s: string): string {
    let h = 5381;
    for (let i = 0; i < s.length; i++) {
        h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    }
    return (h >>> 0).toString(36);
}

// Reconciliation primitives shared by transcript.ts and marginalia.ts.
//
// A keyed item with a matching key + hash on an existing child is reused
// in place — the element reference is carried through unchanged, which
// preserves hover state, active transitions, and attached event listeners.
// Keyless items are always rebuilt via build() (e.g. review findings).
// build() is lazy: only called when no reusable existing element is found.
export interface ReconcileItem {
    key?: string;
    hash?: string;
    build: () => HTMLElement;
}

export function reconcileKeyed(
    container: HTMLElement,
    items: ReconcileItem[],
    keyAttr: string,
    hashAttr: string = 'hash',
): void {
    // Index existing children by their key data-attribute so we can look
    // up potential reuse candidates in O(1) during the build pass.
    const reusable = new Map<string, HTMLElement>();
    for (const child of Array.from(container.children)) {
        const el = child as HTMLElement;
        const k = el.dataset[keyAttr];
        if (k) {
            reusable.set(k, el);
        }
    }

    const newChildren: HTMLElement[] = items.map(item => {
        if (item.key) {
            const existing = reusable.get(item.key);
            if (existing && existing.dataset[hashAttr] === item.hash) {
                return existing;
            }
        }
        return item.build();
    });

    // Minimal-mutation diff: only replace / append / remove where the
    // reference at a given index actually differs from what was there.
    const oldChildren = Array.from(container.children) as HTMLElement[];
    const n = Math.max(oldChildren.length, newChildren.length);
    for (let i = 0; i < n; i++) {
        const oldCh = oldChildren[i] as HTMLElement | undefined;
        const newCh = newChildren[i];
        if (!oldCh) {
            container.appendChild(newCh);
        } else if (!newCh) {
            container.removeChild(oldCh);
        } else if (oldCh !== newCh) {
            container.replaceChild(newCh, oldCh);
        }
    }
}

export function formatTokens(n: number): string {
    if (n >= 1_000_000) {
        return (n / 1_000_000).toFixed(1) + 'M';
    }
    if (n >= 1_000) {
        return (n / 1_000).toFixed(1) + 'K';
    }
    return String(n);
}
