import axios, { AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';

import { resolveApiUrl } from '../../api/urls';
import { getAccessToken, handleUnauthorized } from './auth';
import { normalizeHttpError, notifyHttpError } from './errors';
import { IDEMPOTENCY_KEY_HEADER, resolveIdempotencyKey } from './idempotency';
import { createRequestId, REQUEST_ID_HEADER } from './trace';

type AuthAwareRequestConfig = InternalAxiosRequestConfig & {
    /** Token stamped at request time for delayed-401 identity matching. */
    authToken?: string | null;
};

const httpClient = axios.create({
    timeout: 30000,
});

export const createAuthorizedHeaders = (
    headers: Record<string, string> = {},
    options: { idempotencyKey?: string | null } = {},
): Record<string, string> => {
    const nextHeaders = { ...headers };
    const token = getAccessToken();
    const hasRequestId = REQUEST_ID_HEADER in nextHeaders || REQUEST_ID_HEADER.toLowerCase() in nextHeaders;
    const hasIdempotencyKey =
        IDEMPOTENCY_KEY_HEADER in nextHeaders || IDEMPOTENCY_KEY_HEADER.toLowerCase() in nextHeaders;

    if (!hasRequestId) {
        nextHeaders[REQUEST_ID_HEADER] = createRequestId();
    }

    if (options.idempotencyKey && !hasIdempotencyKey) {
        nextHeaders[IDEMPOTENCY_KEY_HEADER] = resolveIdempotencyKey(options.idempotencyKey);
    }

    if (token && !('Authorization' in nextHeaders) && !('authorization' in nextHeaders)) {
        nextHeaders.Authorization = `Bearer ${token}`;
    }

    return nextHeaders;
};

httpClient.interceptors.request.use(
    (config: AuthAwareRequestConfig) => {
        const headers = AxiosHeaders.from(config.headers);
        const token = getAccessToken();
        // Stamp request-time identity so delayed 401s can be matched correctly.
        config.authToken = token;

        if (config.url) {
            config.url = resolveApiUrl(config.url);
        }

        if (token && !headers.has('Authorization')) {
            headers.set('Authorization', `Bearer ${token}`);
        }

        if (!headers.has(REQUEST_ID_HEADER)) {
            headers.set(REQUEST_ID_HEADER, createRequestId());
        }

        config.headers = headers;
        return config;
    },
    (error) => Promise.reject(error),
);

httpClient.interceptors.response.use(
    (response) => {
        if (import.meta.env.DEV) {
            const traceId = response.headers['x-trace-id'];
            const requestId = response.headers['x-request-id'];
            const method = response.config.method?.toUpperCase() ?? '?';
            const url = response.config.url ?? '';
            const status = response.status;
            if (traceId || requestId) {
                console.log(
                    `%c[trace] %c${method} ${url} ${status}`,
                    'color:#6366f1;font-weight:bold',
                    'color:#94a3b8',
                    `\n  x-trace-id:   ${traceId ?? '—'}`,
                    `\n  x-request-id: ${requestId ?? '—'}`,
                );
            }
        }
        return response.data;
    },
    (error) => {
        if (import.meta.env.DEV && error?.response) {
            const traceId = error.response.headers?.['x-trace-id'];
            const requestId = error.response.headers?.['x-request-id'];
            const method = error.config?.method?.toUpperCase() ?? '?';
            const url = error.config?.url ?? '';
            const status = error.response.status;
            if (traceId || requestId) {
                console.log(
                    `%c[trace] %c${method} ${url} ${status} ❌`,
                    'color:#ef4444;font-weight:bold',
                    'color:#94a3b8',
                    `\n  x-trace-id:   ${traceId ?? '—'}`,
                    `\n  x-request-id: ${requestId ?? '—'}`,
                );
            }
        }

        const normalized = normalizeHttpError(error);
        const isMeRequest = error.config?.url?.endsWith('/users/me');
        const requestToken =
            (error.config as AuthAwareRequestConfig | undefined)?.authToken ?? null;

        if (normalized.code === 'unauthorized' || (isMeRequest && normalized.code === 'forbidden')) {
            handleUnauthorized(requestToken);
        }

        if (!isMeRequest) {
            notifyHttpError(normalized);
        }

        return Promise.reject(normalized);
    },
);

export default httpClient;
