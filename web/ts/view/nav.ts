// ── Nav View ──

import {buildEmitter} from '../events';
import {tmpl} from './utils';
import {NavView, JobMeta} from '../types';

export function buildNavView(): NavView {
    const {on, emit} = buildEmitter(),
        elNav = document.getElementById('transcriptNav');

    function render(jobs: JobMeta[], activeJobId: string | null): void {
        if (!elNav) {
            return;
        }

        elNav.querySelectorAll('.transcript-pill').forEach(elPill => elPill.remove());

        jobs.forEach(job => {
            const elPill = tmpl('tmpl-nav-pill'),
                status = job.status || 'init';

            elPill.dataset.jobId = job.id;
            if (job.id === activeJobId) {
                elPill.classList.add('active');
            }
            elPill.querySelector('.pill-dot')!.className = 'pill-dot ' + status;
            elPill.querySelector('.pill-title')!.textContent = job.title || job.id;
            if (status === 'ingesting' || status === 'analysing' || status === 'reviewing') {
                (elPill.querySelector('.pill-live') as HTMLElement).hidden = false;
            }

            elNav.appendChild(elPill);
        });
    }

    elNav!.addEventListener('click', (e: MouseEvent) => {
        const elPill = (e.target as HTMLElement).closest('[data-action="select-job"]') as HTMLElement | null;
        if (elPill) {
            emit('selectJob', elPill.dataset.jobId);
            return;
        }
        const elNewBtn = (e.target as HTMLElement).closest('[data-action="open-modal"]');
        if (elNewBtn) {
            emit('openModal');
            return;
        }
    });

    return {on, render};
}
