import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { API_URLS, resolveApiUrl } from '../../api/urls';
import { AppHttpError } from './errors';
import {
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
                message: 'Internal Server Error',
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
            message: 'Internal Server Error',
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
});
