import axios from 'axios';

import { getRequestIdFromHeaders } from './trace';

export type AppHttpErrorCode =
    | 'network'
    | 'unauthorized'
    | 'forbidden'
    | 'validation'
    | 'server'
    | 'unknown';

type AppHttpErrorParams = {
    code: AppHttpErrorCode;
    message: string;
    status?: number;
    requestId?: string;
    details?: unknown;
};

export class AppHttpError extends Error {
    code: AppHttpErrorCode;
    status?: number;
    requestId?: string;
    details?: unknown;

    constructor({ code, message, status, requestId, details }: AppHttpErrorParams) {
        super(message);
        this.name = 'AppHttpError';
        this.code = code;
        this.status = status;
        this.requestId = requestId;
        this.details = details;
    }
}

const extractMessage = (data: unknown, fallback: string): string => {
    if (typeof data === 'string' && data.trim()) {
        return data;
    }

    if (data && typeof data === 'object') {
        const maybeObject = data as Record<string, unknown>;
        const message = maybeObject.message;
        const detail = maybeObject.detail;

        if (typeof message === 'string' && message.trim()) {
            return message;
        }

        if (typeof detail === 'string' && detail.trim()) {
            return detail;
        }
    }

    return fallback;
};

export const getHttpErrorCode = (status?: number): AppHttpErrorCode => {
    if (status === 401) {
        return 'unauthorized';
    }

    if (status === 403) {
        return 'forbidden';
    }

    if (status === 400 || status === 422) {
        return 'validation';
    }

    if (typeof status === 'number' && status >= 500) {
        return 'server';
    }

    if (typeof status === 'number') {
        return 'unknown';
    }

    return 'network';
};

export const normalizeHttpError = (error: unknown): AppHttpError => {
    if (error instanceof AppHttpError) {
        return error;
    }

    if (axios.isAxiosError(error)) {
        const status = error.response?.status;
        const code = getHttpErrorCode(status);
        const requestId = getRequestIdFromHeaders(error.response?.headers);
        return new AppHttpError({
            code,
            status,
            requestId,
            details: error.response?.data,
            message: extractMessage(
                error.response?.data,
                code === 'network' ? '网络连接失败' : error.message || '网络请求错误',
            ),
        });
    }

    if (error instanceof Error) {
        return new AppHttpError({
            code: 'network',
            message: error.message || '网络连接失败',
        });
    }

    return new AppHttpError({
        code: 'unknown',
        message: '网络请求错误',
        details: error,
    });
};

export const createFetchHttpError = (params: {
    status: number;
    statusText: string;
    requestId?: string;
    details?: unknown;
}): AppHttpError => {
    const code = getHttpErrorCode(params.status);
    return new AppHttpError({
        code,
        status: params.status,
        requestId: params.requestId,
        details: params.details,
        message: extractMessage(params.details, `HTTP ${params.status}: ${params.statusText}`),
    });
};
