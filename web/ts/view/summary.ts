// ── Summary View ──

import {buildEmitter} from '../events';
import {tmpl, makeEl, formatTokens} from './utils';
import {SummaryView, SummaryData} from '../types';

export function buildSummaryView(): SummaryView {
    const {on, emit} = buildEmitter(),
        elCol = document.getElementById('summaryCol');

    function makeUsageItem(key: string, value: string): HTMLElement {
        const elItem = tmpl('tmpl-usage-item');
        elItem.querySelector('.usage-key')!.textContent = key;
        elItem.querySelector('.usage-value')!.textContent = value;
        return elItem;
    }

    function render(data: SummaryData | null): void {
        if (!elCol) {
            return;
        }
        elCol.innerHTML = '';
        if (!data) {
            return;
        }

        const {title, status, context, stats, verdicts, llmStats} = data;

        // Title
        elCol.appendChild(makeEl('h1', 'headline', title));

        // Metadata
        const elMetaTable = makeEl('div', 'meta-table'),
            metaFields: [string, string | undefined][] = [
                ['Speaker', context.speakers],
                ['Date', context.date_and_time],
                ['Location', context.location],
                ['Background', context.background],
            ];
        metaFields.forEach(([key, val]) => {
            if (!val) {
                return;
            }
            const elRow = tmpl('tmpl-meta-row');
            elRow.querySelector('.meta-key')!.textContent = key;
            elRow.querySelector('.meta-value')!.textContent = val;
            elMetaTable.appendChild(elRow);
        });
        elCol.appendChild(elMetaTable);

        // Annotation stats
        elCol.appendChild(makeEl('div', 'section-label', 'Annotations Found'));
        const elStatsGrid = makeEl('div', 'stats-grid'),
            statPairs: [string, number][] = [
                ['Claims', stats.claims], ['Predictions', stats.predictions],
                ['Commitments', stats.commitments], ['Fallacies', stats.fallacies],
                ['Rhetoric', stats.rhetoric], ['Tactics', stats.tactics],
            ];
        statPairs.forEach(([label, count]) => {
            const elCell = tmpl('tmpl-stat-cell');
            elCell.querySelector('.stat-number')!.textContent = String(count);
            elCell.querySelector('.stat-label')!.textContent = label;
            elStatsGrid.appendChild(elCell);
        });
        elCol.appendChild(elStatsGrid);

        // Verdict breakdown
        elCol.appendChild(makeEl('div', 'section-label', 'Fact-Check Verdicts'));
        const elVerdicts = makeEl('div', ''),
            totalChecks = Math.max(1,
                verdicts.established + verdicts.misleading + verdicts.unsupported + verdicts.false + verdicts.pending),
            verdictRows: [string, number, string][] = [
                ['Established', verdicts.established, 'established'],
                ['Misleading', verdicts.misleading, 'misleading'],
                ['Unsupported', verdicts.unsupported, 'unsupported'],
                ['False', verdicts.false, 'false'],
                ['Pending', verdicts.pending, 'pending'],
            ];
        elVerdicts.style.marginBottom = '20px';
        verdictRows.forEach(([label, count, cls]) => {
            const pct = Math.round((count / totalChecks) * 100),
                elRow = tmpl('tmpl-verdict-row'),
                elFill = elRow.querySelector('.verdict-bar-fill') as HTMLElement;
            elRow.querySelector('.verdict-name')!.textContent = label;
            elFill.style.width = pct + '%';
            elFill.classList.add(cls);
            elRow.querySelector('.verdict-count')!.textContent = String(count);
            elVerdicts.appendChild(elRow);
        });
        elCol.appendChild(elVerdicts);

        // Token usage — per-model breakdown
        elCol.appendChild(makeEl('div', 'section-label', 'Token Usage'));
        if (llmStats && llmStats.length > 0) {
            llmStats.forEach(s => {
                elCol.appendChild(makeEl('div', 'usage-model-label', s.model));
                elCol.appendChild(makeUsageItem('Input', formatTokens(s.input_tokens)));
                elCol.appendChild(makeUsageItem('Output', formatTokens(s.output_tokens)));
                if (s.cache_read_tokens > 0) {
                    elCol.appendChild(makeUsageItem('Cache reads', formatTokens(s.cache_read_tokens)));
                }
                if (s.cache_creation_tokens > 0) {
                    elCol.appendChild(makeUsageItem('Cache writes', formatTokens(s.cache_creation_tokens)));
                }
            });
        }

        // Delete button
        const elDeleteBtn = makeEl('button', 'btn-delete-job', 'Delete Transcript');
        (elDeleteBtn as HTMLElement).dataset.action = 'delete-job';
        elCol.appendChild(elDeleteBtn);
    }

    elCol!.addEventListener('click', (e: MouseEvent) => {
        const elDeleteBtn = (e.target as HTMLElement).closest('[data-action="delete-job"]');
        if (elDeleteBtn) {
            emit('deleteJob');
            return;
        }
    });

    return {on, render};
}
