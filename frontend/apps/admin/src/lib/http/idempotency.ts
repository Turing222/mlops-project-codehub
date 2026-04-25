import { createRequestId } from './trace';

export const IDEMPOTENCY_KEY_HEADER = 'X-Idempotency-Key';

export const createIdempotencyKey = (): string => {
    return createRequestId();
};

export const resolveIdempotencyKey = (idempotencyKey?: string | null): string => {
    if (typeof idempotencyKey === 'string' && idempotencyKey.trim()) {
        return idempotencyKey;
    }

    return createIdempotencyKey();
};
