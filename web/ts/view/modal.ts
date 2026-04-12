// ── Modal View (New Transcript) ──

import {buildEmitter} from '../events';
import {wireDropZone} from './utils';
import {ModalView, TranscriptFormData} from '../types';

export function buildModalView(): ModalView {
    const {on, emit} = buildEmitter(),
        elOverlay = document.getElementById('modalOverlay')!;

    function open(): void {
        elOverlay.classList.add('visible');
        const elDatetime = document.getElementById('job-datetime') as HTMLInputElement | null;
        if (elDatetime) {
            elDatetime.value = new Date().toISOString().slice(0, 16).replace('T', ' ');
        }
    }

    function close(): void {
        elOverlay.classList.remove('visible');
        document.querySelectorAll('.modal input, .modal textarea').forEach(el => {
            (el as HTMLInputElement).value = '';
        });
        document.getElementById('fileName')!.textContent = '';
        (document.getElementById('mp3File') as HTMLInputElement).value = '';
        document.getElementById('playFileName')!.textContent = '';
        (document.getElementById('playMp3File') as HTMLInputElement).value = '';
        switchTab('text');
    }

    function switchTab(name: string): void {
        document.querySelectorAll('.tab').forEach(el => {
            const elTab = el as HTMLElement;
            elTab.classList.toggle('active', elTab.dataset.tab === name);
        });
        document.querySelectorAll('.tab-content').forEach(el => {
            const elPane = el as HTMLElement;
            elPane.classList.toggle('active', elPane.id === 'tab-' + name);
        });
    }

    function getFormData(): TranscriptFormData {
        const activeTab = (document.querySelector('.tab.active') as HTMLElement).dataset.tab!;
        return {
            tab: activeTab,
            title: (document.getElementById('job-title') as HTMLInputElement).value,
            speakers: (document.getElementById('job-speakers') as HTMLInputElement).value,
            datetime: (document.getElementById('job-datetime') as HTMLInputElement).value,
            location: (document.getElementById('job-location') as HTMLInputElement).value,
            background: (document.getElementById('job-background') as HTMLTextAreaElement).value,
            transcript: activeTab === 'text' ? (document.getElementById('text-transcript') as HTMLTextAreaElement).value : '',
            mp3File: activeTab === 'mp3' ? (document.getElementById('mp3File') as HTMLInputElement).files![0] || null : null,
            playMp3File: activeTab === 'play-mp3' ? (document.getElementById('playMp3File') as HTMLInputElement).files![0] || null : null,
        };
    }

    elOverlay.addEventListener('click', (e: MouseEvent) => {
        const elTabBtn = (e.target as HTMLElement).closest('.tab[data-tab]') as HTMLElement | null;
        if (elTabBtn) {
            switchTab(elTabBtn.dataset.tab!);
            return;
        }
        if ((e.target as HTMLElement).closest('[data-action="close-modal"]')) {
            close();
            return;
        }
        if ((e.target as HTMLElement).closest('[data-action="submit-transcript"]')) {
            emit('submitTranscript', getFormData());
            return;
        }
    });

    // Drop zones
    const elDropZone = document.getElementById('dropZone'),
        elMp3Input = document.getElementById('mp3File') as HTMLInputElement | null;
    if (elDropZone && elMp3Input) {
        wireDropZone(elDropZone, elMp3Input, (file: File) => {
            document.getElementById('fileName')!.textContent = file.name;
        });
    }

    const elPlayDropZone = document.getElementById('playDropZone'),
        elPlayMp3Input = document.getElementById('playMp3File') as HTMLInputElement | null;
    if (elPlayDropZone && elPlayMp3Input) {
        wireDropZone(elPlayDropZone, elPlayMp3Input, (file: File) => {
            document.getElementById('playFileName')!.textContent = file.name;
        });
    }

    return {on, open, close};
}
