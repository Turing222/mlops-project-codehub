import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppHttpError } from '../lib/http/errors';

const reportFrontendHttpError = vi.fn();

vi.mock('../lib/http/telemetry', () => ({
    reportFrontendHttpError,
}));

describe('query client telemetry hook', () => {
    beforeEach(() => {
        reportFrontendHttpError.mockClear();
    });

    it('reports failed queries through the query cache error callback', async () => {
        const { queryClient } = await import('./query-client');
        const error = new AppHttpError({
            code: 'server',
            status: 500,
            message: 'Internal Server Error',
            requestId: 'req-500',
        });

        await expect(
            queryClient.fetchQuery({
                queryKey: ['telemetry-test-query'],
                queryFn: async () => {
                    throw error;
                },
                retry: false,
            }),
        ).rejects.toBe(error);

        expect(reportFrontendHttpError).toHaveBeenCalledWith(error, 'react_query');
        queryClient.clear();
    });

    it('reports failed mutations through the mutation cache error callback', async () => {
        const { queryClient } = await import('./query-client');
        const error = new AppHttpError({
            code: 'server',
            status: 500,
            message: 'Internal Server Error',
            requestId: 'req-501',
        });

        const mutation = queryClient.getMutationCache().build(queryClient, {
            mutationKey: ['telemetry-test-mutation'],
            mutationFn: async () => {
                throw error;
            },
            retry: false,
        });

        await expect(mutation.execute(undefined)).rejects.toBe(error);

        expect(reportFrontendHttpError).toHaveBeenCalledWith(
            error,
            'react_query_mutation',
        );
        queryClient.clear();
    });
});
