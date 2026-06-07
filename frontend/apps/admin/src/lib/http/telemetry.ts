import { API_URLS, resolveApiUrl } from '../../api/urls';
import { AppHttpError } from './errors';

export type FrontendErrorEventType =
    | 'http_error'
    | 'render_error'
    | 'global_error'
    | 'unhandled_rejection'
    | 'stream_error';

export type FrontendErrorMetadataValue = string | number | boolean | null;

export type FrontendErrorEventInput = {
    eventType: FrontendErrorEventType;
    message: string;
    source: string;
    requestId?: string;
    status?: number;
    errorCode?: string;
    url?: string;
    method?: string;
    metadata?: Record<string, FrontendErrorMetadataValue>;
};

type FrontendErrorEventPayload = FrontendErrorEventInput & {
    severity: 'error';
};

type ReportableAppHttpError = AppHttpError & { requestId: string };

const DEDUPE_TTL_MS = 5000;
// Keep payloads within the backend's bounded telemetry schema so events are not dropped as 422.
const MAX_MESSAGE_LENGTH = 500;
const MAX_METADATA_KEYS = 20;
const MAX_METADATA_VALUE_LENGTH = 2048;
const recentReports = new Map<string, number>();

const truncate = (value: string, max: number): string =>
    value.length > max ? value.slice(0, max) : value;

/**
 * 把任意 thrown 值（Error、AppHttpError、字符串、任意 rejection reason）归一化为可读 message。
 */
export const normalizeErrorMessage = (error: unknown): string => {
    if (typeof error === 'string') {
        return error.trim() || 'Unknown error';
    }
    if (error instanceof Error) {
        return error.message || error.name || 'Unknown error';
    }
    if (error && typeof error === 'object') {
        const maybeMessage = (error as { message?: unknown }).message;
        if (typeof maybeMessage === 'string' && maybeMessage.trim()) {
            return maybeMessage;
        }
        try {
            return JSON.stringify(error);
        } catch {
            return 'Unknown error';
        }
    }
    if (error === null || error === undefined) {
        return 'Unknown error';
    }
    return String(error);
};

const isReportableServerError = (error: unknown): error is ReportableAppHttpError => {
    if (!(error instanceof AppHttpError) || !error.requestId) {
        return false;
    }
    return error.code === 'server' || (typeof error.status === 'number' && error.status >= 500);
};

const buildDedupeKey = (payload: FrontendErrorEventPayload): string =>
    [
        payload.eventType,
        payload.source,
        payload.message,
        payload.requestId ?? '',
        payload.status ?? '',
        payload.errorCode ?? '',
    ].join('|');

const pruneExpiredReports = (now: number): void => {
    for (const [key, reportedAt] of recentReports) {
        if (now - reportedAt >= DEDUPE_TTL_MS) {
            recentReports.delete(key);
        }
    }
};

const shouldReport = (payload: FrontendErrorEventPayload, now = Date.now()): boolean => {
    pruneExpiredReports(now);

    const key = buildDedupeKey(payload);
    const lastReportedAt = recentReports.get(key);

    if (lastReportedAt !== undefined && now - lastReportedAt < DEDUPE_TTL_MS) {
        return false;
    }

    recentReports.set(key, now);
    return true;
};

const boundMetadata = (
    metadata?: Record<string, FrontendErrorMetadataValue>,
): Record<string, FrontendErrorMetadataValue> | undefined => {
    if (!metadata) {
        return undefined;
    }
    const bounded: Record<string, FrontendErrorMetadataValue> = {};
    // Mirror the backend bounds (≤20 keys, bounded value length) so the event is accepted, not 422'd.
    for (const [key, value] of Object.entries(metadata).slice(0, MAX_METADATA_KEYS)) {
        bounded[key] =
            typeof value === 'string' ? truncate(value, MAX_METADATA_VALUE_LENGTH) : value;
    }
    return bounded;
};

export const sendFrontendErrorTelemetry = (payload: FrontendErrorEventPayload): void => {
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

/**
 * 通用前端错误事件上报入口：补 severity、截断越界字段、短 TTL 去重后发送。
 */
export const reportFrontendErrorEvent = (input: FrontendErrorEventInput): void => {
    const payload: FrontendErrorEventPayload = {
        ...input,
        message: truncate(input.message, MAX_MESSAGE_LENGTH),
        metadata: boundMetadata(input.metadata),
        severity: 'error',
    };

    if (!shouldReport(payload)) {
        return;
    }

    sendFrontendErrorTelemetry(payload);
};

/**
 * HTTP 5xx 兼容入口：仅上报带 requestId 的服务端错误，内部走通用 `http_error` 事件语义。
 */
export const reportFrontendHttpError = (error: unknown, source: string): void => {
    if (!isReportableServerError(error)) {
        return;
    }

    reportFrontendErrorEvent({
        eventType: 'http_error',
        message: error.message,
        source,
        status: error.status ?? 500,
        errorCode: error.code,
        requestId: error.requestId,
        url: error.url,
        method: error.method,
    });
};

export const resetFrontendTelemetryDedupeForTests = (): void => {
    recentReports.clear();
};
