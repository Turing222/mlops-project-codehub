import axios, { AxiosHeaders } from 'axios';
import { message } from 'antd';

import { clearAccessToken, getAccessToken, notifyUnauthorized } from './auth';
import { AppHttpError, normalizeHttpError } from './errors';
import { IDEMPOTENCY_KEY_HEADER, resolveIdempotencyKey } from './idempotency';
import { createRequestId, REQUEST_ID_HEADER } from './trace';

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

const notifyHttpError = (error: AppHttpError): void => {
    switch (error.code) {
        case 'unauthorized':
            message.warning('请登录以使用完整功能');
            return;
        case 'forbidden':
            message.error('没有权限执行此操作');
            return;
        case 'network':
            message.error('网络连接失败');
            return;
        default:
            message.error(error.message || '网络请求错误');
    }
};

httpClient.interceptors.request.use(
    (config) => {
        const headers = AxiosHeaders.from(config.headers);
        const token = getAccessToken();

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
    (response) => response.data,
    (error) => {
        const normalized = normalizeHttpError(error);

        if (normalized.code === 'unauthorized') {
            clearAccessToken();
            notifyUnauthorized();
        }

        notifyHttpError(normalized);
        return Promise.reject(normalized);
    },
);

export default httpClient;
