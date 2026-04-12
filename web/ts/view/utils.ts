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

export function formatTokens(n: number): string {
    if (n >= 1_000_000) {
        return (n / 1_000_000).toFixed(1) + 'M';
    }
    if (n >= 1_000) {
        return (n / 1_000).toFixed(1) + 'K';
    }
    return String(n);
}
