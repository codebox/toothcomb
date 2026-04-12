// ── Confirmation Modals ──

import {buildEmitter} from '../events';
import {ConfirmModal} from '../types';

export function buildDeleteModal(): ConfirmModal {
    const {on, emit} = buildEmitter(),
        elOverlay = document.getElementById('deleteModalOverlay')!,
        elTitle = document.getElementById('deleteJobTitle')!;
    let pendingJobId: string | null = null;

    function open(jobId: string, title?: string): void {
        pendingJobId = jobId;
        elTitle.textContent = title || jobId;
        elOverlay.classList.add('visible');
    }

    function close(): void {
        elOverlay.classList.remove('visible');
        pendingJobId = null;
    }

    elOverlay.addEventListener('click', (e: MouseEvent) => {
        if ((e.target as HTMLElement).closest('[data-action="confirm-delete"]')) {
            if (pendingJobId) {
                emit('confirmDelete', pendingJobId);
            }
            close();
            return;
        }
        if ((e.target as HTMLElement).closest('[data-action="cancel-delete"]')) {
            close();
            return;
        }
    });

    return {on, open, close};
}

export function buildAbortModal(): ConfirmModal {
    const {on, emit} = buildEmitter(),
        elOverlay = document.getElementById('abortModalOverlay')!;

    function open(): void {
        elOverlay.classList.add('visible');
    }

    function close(): void {
        elOverlay.classList.remove('visible');
    }

    elOverlay.addEventListener('click', (e: MouseEvent) => {
        if ((e.target as HTMLElement).closest('[data-action="confirm-abort"]')) {
            emit('confirmAbort');
            close();
            return;
        }
        if ((e.target as HTMLElement).closest('[data-action="cancel-abort"]')) {
            close();
            return;
        }
    });

    return {on, open, close};
}
