export const REQUEST_ID_HEADER = 'X-Request-ID';

export const createRequestId = (): string => {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    return `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
};

export const getRequestIdFromHeaders = (
    headers?: Headers | Record<string, unknown>,
): string | undefined => {
    if (!headers) {
        return undefined;
    }

    if (headers instanceof Headers) {
        return headers.get(REQUEST_ID_HEADER) ?? headers.get(REQUEST_ID_HEADER.toLowerCase()) ?? undefined;
    }

    const requestId = headers[REQUEST_ID_HEADER] ?? headers[REQUEST_ID_HEADER.toLowerCase()];
    return typeof requestId === 'string' ? requestId : undefined;
};
