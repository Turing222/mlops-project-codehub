import { describe, expect, it } from 'vitest';

import { AppHttpError } from './errors';
import { applyMutationPolicy } from './mutation-policy';

describe('mutation-policy', () => {
    it('no-retry policy returns retry: false', () => {
        const result = applyMutationPolicy({ policy: 'no-retry' });
        expect(result.retry).toBe(false);
    });

    it('idempotent policy retries on network error up to 1 time', () => {
        const result = applyMutationPolicy({ policy: 'idempotent' });
        const retryFn = result.retry as (failureCount: number, error: unknown) => boolean;
        expect(retryFn(0, new AppHttpError({ code: 'network', message: 'network error' }))).toBe(true);
        expect(retryFn(1, new AppHttpError({ code: 'network', message: 'network error' }))).toBe(false);
    });

    it('idempotent policy does not retry on 401/403/422', () => {
        const result = applyMutationPolicy({ policy: 'idempotent' });
        const retryFn = result.retry as (failureCount: number, error: unknown) => boolean;
        expect(retryFn(0, new AppHttpError({ code: 'unauthorized', message: 'unauthorized', status: 401 }))).toBe(false);
        expect(retryFn(0, new AppHttpError({ code: 'forbidden', message: 'forbidden', status: 403 }))).toBe(false);
        expect(retryFn(0, new AppHttpError({ code: 'validation', message: 'validation', status: 422 }))).toBe(false);
    });

    it('idempotent policy retries on 5xx', () => {
        const result = applyMutationPolicy({ policy: 'idempotent' });
        const retryFn = result.retry as (failureCount: number, error: unknown) => boolean;
        const serverError = new AppHttpError({ code: 'server', message: 'internal error', status: 500 });
        expect(retryFn(0, serverError)).toBe(true);
    });

    it('safe policy retries up to 2 times on 5xx', () => {
        const result = applyMutationPolicy({ policy: 'safe' });
        const retryFn = result.retry as (failureCount: number, error: unknown) => boolean;
        const serverError = new AppHttpError({ code: 'server', message: 'internal error', status: 500 });
        expect(retryFn(0, serverError)).toBe(true);
        expect(retryFn(1, serverError)).toBe(true);
        expect(retryFn(2, serverError)).toBe(false);
    });

    it('safe policy does not retry on 401', () => {
        const result = applyMutationPolicy({ policy: 'safe' });
        const retryFn = result.retry as (failureCount: number, error: unknown) => boolean;
        expect(retryFn(0, new AppHttpError({ code: 'unauthorized', message: 'unauthorized', status: 401 }))).toBe(false);
    });

    it('custom maxRetries overrides defaults', () => {
        const result = applyMutationPolicy({ policy: 'idempotent', maxRetries: 3 });
        const retryFn = result.retry as (failureCount: number, error: unknown) => boolean;
        const networkError = new AppHttpError({ code: 'network', message: 'network error' });
        expect(retryFn(2, networkError)).toBe(true);
        expect(retryFn(3, networkError)).toBe(false);
    });

    it('retries on 429 rate limit', () => {
        const result = applyMutationPolicy({ policy: 'idempotent' });
        const retryFn = result.retry as (failureCount: number, error: unknown) => boolean;
        const rateLimitError = new AppHttpError({ code: 'unknown', message: 'too many requests', status: 429 });
        expect(retryFn(0, rateLimitError)).toBe(true);
    });
});
