import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { API_URLS, resolveApiUrl } from '../../api/urls';
import { AppHttpError } from './errors';
import {
    normalizeErrorMessage,
    reportFrontendErrorEvent,
    reportFrontendHttpError,
    resetFrontendTelemetryDedupeForTests,
    sendFrontendErrorTelemetry,
} from './telemetry';

describe('frontend error telemetry', () => {
    beforeEach(() => {
        resetFrontendTelemetryDedupeForTests();
    });

    afterEach(() => {
        vi.unstubAllEnvs();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    it('reports server AppHttpError with request id through sendBeacon', () => {
        const sendBeacon = vi.fn().mockReturnValue(true);
        const fetchMock = vi.fn();
        vi.stubGlobal('navigator', { sendBeacon });
        vi.stubGlobal('fetch', fetchMock);

        reportFrontendHttpError(
            new AppHttpError({
                code: 'server',
                status: 500,
                message: 'Internal Server Error',
                requestId: 'req-500',
                url: '/api/v1/users/me',
                method: 'GET',
            }),
            'react_query',
        );

        expect(sendBeacon).toHaveBeenCalledTimes(1);
        expect(sendBeacon).toHaveBeenCalledWith(resolveApiUrl(API_URLS.TELEMETRY.ERRORS), expect.any(Blob));
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('does not report non-server or request-id-less errors', () => {
        const sendBeacon = vi.fn().mockReturnValue(true);
        vi.stubGlobal('navigator', { sendBeacon });

        reportFrontendHttpError(
            new AppHttpError({
                code: 'forbidden',
                status: 403,
                message: 'Forbidden',
                requestId: 'req-403',
            }),
            'react_query',
        );
        reportFrontendHttpError(
            new AppHttpError({
                code: 'server',
                status: 500,
                message: 'Internal Server Error',
            }),
            'react_query',
        );

        expect(sendBeacon).not.toHaveBeenCalled();
    });

    it('falls back to fetch and swallows telemetry failures', () => {
        const sendBeacon = vi.fn().mockReturnValue(false);
        const fetchMock = vi.fn().mockRejectedValue(new Error('offline'));
        vi.stubGlobal('navigator', { sendBeacon });
        vi.stubGlobal('fetch', fetchMock);

        expect(() => {
            sendFrontendErrorTelemetry({
                eventType: 'http_error',
                message: 'Internal Server Error',
                source: 'react_query',
                severity: 'error',
                status: 500,
                errorCode: 'server',
                requestId: 'req-500',
            });
        }).not.toThrow();

        expect(fetchMock).toHaveBeenCalledWith(
            resolveApiUrl(API_URLS.TELEMETRY.ERRORS),
            expect.objectContaining({
                method: 'POST',
                keepalive: true,
            }),
        );
    });

    it('uses absolute telemetry URLs when VITE_API_BASE_URL is configured', () => {
        const sendBeacon = vi.fn().mockReturnValue(true);
        vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com');
        vi.stubGlobal('navigator', { sendBeacon });

        sendFrontendErrorTelemetry({
            eventType: 'http_error',
            message: 'Internal Server Error',
            source: 'react_query',
            severity: 'error',
            status: 500,
            errorCode: 'server',
            requestId: 'req-500',
        });

        expect(sendBeacon).toHaveBeenCalledWith(
            'https://api.example.com/api/v1/telemetry/errors',
            expect.any(Blob),
        );
    });

    it('deduplicates the same server error within a short window', () => {
        vi.useFakeTimers();
        vi.setSystemTime(0);
        const sendBeacon = vi.fn().mockReturnValue(true);
        vi.stubGlobal('navigator', { sendBeacon });

        const error = new AppHttpError({
            code: 'server',
            status: 500,
            message: 'Internal Server Error',
            requestId: 'req-500',
        });

        reportFrontendHttpError(error, 'react_query');
        reportFrontendHttpError(error, 'react_query');

        expect(sendBeacon).toHaveBeenCalledTimes(1);

        vi.setSystemTime(5001);
        reportFrontendHttpError(error, 'react_query');

        expect(sendBeacon).toHaveBeenCalledTimes(2);
    });

    it('reports a non-HTTP runtime event without requiring http correlation fields', () => {
        const sendBeacon = vi.fn().mockReturnValue(false);
        const fetchMock = vi.fn().mockResolvedValue(undefined);
        vi.stubGlobal('navigator', { sendBeacon });
        vi.stubGlobal('fetch', fetchMock);

        reportFrontendErrorEvent({
            eventType: 'render_error',
            message: 'Cannot read properties of undefined',
            source: 'react_error_boundary',
            metadata: { componentStack: 'at App' },
        });

        expect(fetchMock).toHaveBeenCalledOnce();
        const init = fetchMock.mock.calls[0][1] as RequestInit;
        const body = JSON.parse(init.body as string);
        expect(body).toMatchObject({
            eventType: 'render_error',
            message: 'Cannot read properties of undefined',
            source: 'react_error_boundary',
            severity: 'error',
            metadata: { componentStack: 'at App' },
        });
        expect(body.requestId).toBeUndefined();
        expect(body.status).toBeUndefined();
        expect(body.errorCode).toBeUndefined();
    });

    it('dedupes by event semantics but treats different source/eventType as distinct', () => {
        const sendBeacon = vi.fn().mockReturnValue(true);
        vi.stubGlobal('navigator', { sendBeacon });

        const base = {
            eventType: 'global_error' as const,
            message: 'window blew up',
            source: 'window_error',
        };

        reportFrontendErrorEvent(base);
        reportFrontendErrorEvent(base);
        expect(sendBeacon).toHaveBeenCalledTimes(1);

        reportFrontendErrorEvent({ ...base, source: 'window_unhandledrejection' });
        reportFrontendErrorEvent({ ...base, eventType: 'render_error' });
        expect(sendBeacon).toHaveBeenCalledTimes(3);
    });

    it('truncates overlong messages to the backend bound', () => {
        const sendBeacon = vi.fn().mockReturnValue(false);
        const fetchMock = vi.fn().mockResolvedValue(undefined);
        vi.stubGlobal('navigator', { sendBeacon });
        vi.stubGlobal('fetch', fetchMock);

        reportFrontendErrorEvent({
            eventType: 'global_error',
            message: 'x'.repeat(600),
            source: 'window_error',
        });

        const init = fetchMock.mock.calls[0][1] as RequestInit;
        const body = JSON.parse(init.body as string);
        expect(body.message).toHaveLength(500);
    });

    it('bounds metadata to the backend key limit', () => {
        const sendBeacon = vi.fn().mockReturnValue(false);
        const fetchMock = vi.fn().mockResolvedValue(undefined);
        vi.stubGlobal('navigator', { sendBeacon });
        vi.stubGlobal('fetch', fetchMock);

        const metadata: Record<string, number> = {};
        for (let index = 0; index < 25; index += 1) {
            metadata[`k${index}`] = index;
        }

        reportFrontendErrorEvent({
            eventType: 'render_error',
            message: 'boom',
            source: 'react_error_boundary',
            metadata,
        });

        const init = fetchMock.mock.calls[0][1] as RequestInit;
        const body = JSON.parse(init.body as string);
        expect(Object.keys(body.metadata)).toHaveLength(20);
    });

    describe('normalizeErrorMessage', () => {
        it('extracts a readable message from any thrown value', () => {
            expect(normalizeErrorMessage(new Error('boom'))).toBe('boom');
            expect(normalizeErrorMessage('plain string')).toBe('plain string');
            expect(normalizeErrorMessage({ message: 'object message' })).toBe('object message');
            expect(normalizeErrorMessage(undefined)).toBe('Unknown error');
            expect(normalizeErrorMessage(null)).toBe('Unknown error');
            expect(normalizeErrorMessage(42)).toBe('42');
        });
    });
});
