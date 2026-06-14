import { beforeEach, describe, expect, it, vi } from 'vitest';

const { reportFrontendErrorEvent } = vi.hoisted(() => ({
    reportFrontendErrorEvent: vi.fn(),
}));
vi.mock('../http/telemetry', () => ({
    reportFrontendErrorEvent,
    normalizeErrorMessage: (error: unknown) =>
        error instanceof Error ? error.message : String(error),
}));

import { registerGlobalErrorHandlers, reportI18nInitFailure } from './global-error-handlers';

type MutableErrorEvent = Event & {
    error?: unknown;
    message?: string;
    filename?: string;
    lineno?: number;
    colno?: number;
};

const dispatchWindowError = (error: Error): void => {
    const event = new Event('error') as MutableErrorEvent;
    event.error = error;
    event.message = error.message;
    event.filename = 'app.js';
    event.lineno = 10;
    event.colno = 5;
    window.dispatchEvent(event);
};

const dispatchUnhandledRejection = (reason: unknown): void => {
    const event = new Event('unhandledrejection') as Event & { reason?: unknown };
    event.reason = reason;
    window.dispatchEvent(event);
};

describe('global error handlers', () => {
    beforeEach(() => {
        reportFrontendErrorEvent.mockClear();
        // Idempotent: only the first call across the suite actually attaches listeners.
        registerGlobalErrorHandlers();
    });

    it('reports a global_error for an uncaught window error', () => {
        dispatchWindowError(new Error('global boom'));

        expect(reportFrontendErrorEvent).toHaveBeenCalledWith(
            expect.objectContaining({
                eventType: 'global_error',
                source: 'window_error',
                message: 'global boom',
                metadata: expect.objectContaining({
                    filename: 'app.js',
                    line: 10,
                    column: 5,
                }),
            }),
        );
    });

    it('reports an unhandled_rejection for a rejected promise', () => {
        dispatchUnhandledRejection(new Error('promise boom'));

        expect(reportFrontendErrorEvent).toHaveBeenCalledWith(
            expect.objectContaining({
                eventType: 'unhandled_rejection',
                source: 'window_unhandledrejection',
                message: 'promise boom',
            }),
        );
    });

    it('does not attach duplicate listeners when called repeatedly', () => {
        registerGlobalErrorHandlers();
        registerGlobalErrorHandlers();

        dispatchWindowError(new Error('dup'));

        expect(reportFrontendErrorEvent).toHaveBeenCalledTimes(1);
    });

    it('reports an i18n init failure as a bootstrap global_error', () => {
        reportI18nInitFailure(new Error('i18n down'));

        expect(reportFrontendErrorEvent).toHaveBeenCalledWith(
            expect.objectContaining({
                eventType: 'global_error',
                source: 'i18n_init',
                message: 'i18n down',
            }),
        );
    });
});
