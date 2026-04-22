// ── Toothcomb — View Layer ──
// Composes all sub-views into a single buildView() export.

import {buildNavView} from './nav';
import {buildSummaryView} from './summary';
import {buildTranscriptView} from './transcript';
import {buildMarginaliaView} from './marginalia';
import {buildAnnotationView} from './annotations';
import {buildModalView} from './modal';
import {buildDeleteModal, buildAbortModal} from './confirm-modal';
import {AppView, JobStore} from '../types';

export function buildView(store: JobStore): AppView {
    const elTranscriptCol = document.getElementById('transcriptCol')!,
        elMarginCol = document.getElementById('marginCol')!,
        modal = buildModalView(),
        deleteModal = buildDeleteModal(),
        abortModal = buildAbortModal();

    document.addEventListener('keydown', (e: KeyboardEvent) => {
        if (e.key === 'Escape') {
            modal.close();
            deleteModal.close();
            abortModal.close();
        }
    });

    return {
        nav: buildNavView(),
        summary: buildSummaryView(),
        transcript: buildTranscriptView(),
        marginalia: buildMarginaliaView(),
        annotations: buildAnnotationView(elTranscriptCol, elMarginCol, store),
        modal,
        deleteModal,
        abortModal,
    };
}
