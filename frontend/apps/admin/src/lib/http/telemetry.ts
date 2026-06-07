import { API_URLS, resolveApiUrl } from '../../api/urls';
import { AppHttpError } from './errors';

type FrontendErrorTelemetryPayload = {
    message: string;
    status: number;
    errorCode: string;
    requestId: string;
    url?: string;
    method?: string;
    source?: string;
};

type ReportableAppHttpError = AppHttpError & { requestId: string };

const DEDUPE_TTL_MS = 5000;
const recentReports = new Map<string, number>();

const isReportableServerError = (error: unknown): error is ReportableAppHttpError => {
    if (!(error instanceof AppHttpError) || !error.requestId) {
        return false;
    }
    return error.code === 'server' || (typeof error.status === 'number' && error.status >= 500);
};

const buildDedupeKey = (payload: FrontendErrorTelemetryPayload): string =>
    [payload.requestId, payload.errorCode, payload.status, payload.message].join('|');

const pruneExpiredReports = (now: number): void => {
    for (const [key, reportedAt] of recentReports) {
        if (now - reportedAt >= DEDUPE_TTL_MS) {
            recentReports.delete(key);
        }
    }
};

const shouldReport = (payload: FrontendErrorTelemetryPayload, now = Date.now()): boolean => {
    pruneExpiredReports(now);

    const key = buildDedupeKey(payload);
    const lastReportedAt = recentReports.get(key);

    if (lastReportedAt !== undefined && now - lastReportedAt < DEDUPE_TTL_MS) {
        return false;
    }

    recentReports.set(key, now);
    return true;
};

export const sendFrontendErrorTelemetry = (payload: FrontendErrorTelemetryPayload): void => {
    try {
        const url = resolveApiUrl(API_URLS.TELEMETRY.ERRORS);
        const body = JSON.stringify(payload);

        if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
            const blob = new Blob([body], { type: 'application/json' });
            if (navigator.sendBeacon(url, blob)) {
                return;
            }
        }

        if (typeof fetch === 'function') {
            void fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body,
                keepalive: true,
            }).catch(() => undefined);
        }
    } catch {
        // Telemetry must never affect the user-facing request flow.
    }
};

export const reportFrontendHttpError = (error: unknown, source: string): void => {
    if (!isReportableServerError(error)) {
        return;
    }

    const payload: FrontendErrorTelemetryPayload = {
        message: error.message,
        status: error.status ?? 500,
        errorCode: error.code,
        requestId: error.requestId,
        url: error.url,
        method: error.method,
        source,
    };

    if (!shouldReport(payload)) {
        return;
    }

    sendFrontendErrorTelemetry(payload);
};

export const resetFrontendTelemetryDedupeForTests = (): void => {
    recentReports.clear();
};
