// ── Toothcomb — View Layer ──
// Composes all sub-views into a single buildView() export.

import {buildNavView} from './nav';
import {buildSummaryView} from './summary';
import {buildTranscriptView} from './transcript';
import {buildMarginaliaView} from './marginalia';
import {buildAnnotationView} from './annotations';
import {buildModalView} from './modal';
import {buildDeleteModal, buildAbortModal} from './confirm-modal';
import {AppView} from '../types';

export function buildView(): AppView {
    const elTranscriptCol = document.getElementById('transcriptCol')!,
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
        annotations: buildAnnotationView(elTranscriptCol),
        modal,
        deleteModal,
        abortModal,
    };
}
