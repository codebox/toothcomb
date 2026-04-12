// ── Toothcomb — Event Emitter ──
// Wraps the browser's built-in EventTarget so we get native
// event dispatch without manually iterating listener arrays.

import { Emitter } from './types';

export function buildEmitter(): Emitter {
    const target = new EventTarget();

    function on(event: string, fn: (data?: any) => void): void {
        target.addEventListener(event, e => fn((e as CustomEvent).detail));
    }

    function emit(event: string, data?: any): void {
        target.dispatchEvent(new CustomEvent(event, {detail: data}));
    }

    return {on, emit};
}
