import { AppHttpError } from './errors';

export type MutationPolicy = 'no-retry' | 'idempotent' | 'safe';

export interface MutationPolicyOptions {
    policy: MutationPolicy;
    maxRetries?: number;
}

export const mutationRetry = (
    failureCount: number,
    error: unknown,
    maxRetries: number,
): boolean => {
    if (error instanceof AppHttpError) {
        if (['unauthorized', 'forbidden', 'validation'].includes(error.code)) {
            return false;
        }
        if (error.code === 'server' || error.status === 429) {
            return failureCount < maxRetries;
        }
        if (error.code === 'network') {
            return failureCount < maxRetries;
        }
        return false;
    }
    return failureCount < maxRetries;
};

export function applyMutationPolicy(
    options: MutationPolicyOptions,
): { retry: false | ((failureCount: number, error: unknown) => boolean) } {
    switch (options.policy) {
        case 'no-retry':
            return { retry: false };
        case 'idempotent':
            return {
                retry: (failureCount, error) =>
                    mutationRetry(failureCount, error, options.maxRetries ?? 1),
            };
        case 'safe':
            return {
                retry: (failureCount, error) =>
                    mutationRetry(failureCount, error, options.maxRetries ?? 2),
            };
    }
}
