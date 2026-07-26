import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useRepoAnalysisRunQuery } from './repo-analysis';
import { createTestQueryClient } from '../../test/render-with-query';
import { useAuthStore } from '../../stores/auth-store';

vi.mock('../../api/repo-analysis', () => ({
    getRepoAnalysisRunAPI: vi.fn(),
    submitRepoReadmeCheckAPI: vi.fn(),
}));

vi.mock('./auth', () => ({
    useMeQuery: vi.fn(),
}));

import { getRepoAnalysisRunAPI } from '../../api/repo-analysis';
import { useMeQuery } from './auth';

const mockGetRepoAnalysisRunAPI = vi.mocked(getRepoAnalysisRunAPI);
const mockUseMeQuery = vi.mocked(useMeQuery);

type MeQueryReturn = ReturnType<typeof useMeQuery>;

function mockMe(overrides: Partial<MeQueryReturn> = {}): MeQueryReturn {
    return {
        data: undefined,
        dataUpdatedAt: 0,
        error: null,
        errorUpdatedAt: 0,
        failureCount: 0,
        failureReason: null,
        errorUpdateCount: 0,
        isError: false,
        isFetched: false,
        isFetchedAfterMount: false,
        isFetching: false,
        isPaused: false,
        isLoading: false,
        isLoadingError: false,
        isInitialLoading: false,
        isPending: true,
        isPlaceholderData: false,
        isRefetchError: false,
        isRefetching: false,
        isStale: false,
        isSuccess: false,
        refetch: vi.fn(),
        status: 'pending',
        fetchStatus: 'idle',
        promise: Promise.resolve(undefined),
        ...overrides,
    } as MeQueryReturn;
}

function createWrapper() {
    const queryClient = createTestQueryClient();
    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
}

const runPayload = {
    run: {
        id: 'run-1',
        status: 'succeeded' as const,
        repo_url: 'https://github.com/acme/demo',
        owner: 'acme',
        repo: 'demo',
        rubric_version: 'v1',
        created_at: '',
        updated_at: '',
    },
    report: null,
};

beforeEach(() => {
    useAuthStore.getState().resetAll();
    vi.clearAllMocks();
    mockUseMeQuery.mockReturnValue(mockMe());
    mockGetRepoAnalysisRunAPI.mockResolvedValue(runPayload);
});

describe('useRepoAnalysisRunQuery', () => {
    it('is disabled when runId is null', () => {
        useAuthStore.getState().setToken('tok');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(() => useRepoAnalysisRunQuery(null), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetRepoAnalysisRunAPI).not.toHaveBeenCalled();
    });

    it('is disabled when token is missing even if runId and user exist', () => {
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(() => useRepoAnalysisRunQuery('run-1'), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetRepoAnalysisRunAPI).not.toHaveBeenCalled();
    });

    it('is disabled when bootstrap user is missing even if token and runId exist', () => {
        useAuthStore.getState().setToken('tok');
        mockUseMeQuery.mockReturnValue(mockMe({
            isSuccess: false,
            isPending: false,
            status: 'error',
        }));

        const { result } = renderHook(() => useRepoAnalysisRunQuery('run-1'), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetRepoAnalysisRunAPI).not.toHaveBeenCalled();
    });

    it('is enabled when token, user, and runId are present', async () => {
        useAuthStore.getState().setToken('tok');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(() => useRepoAnalysisRunQuery('run-1'), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });
        expect(mockGetRepoAnalysisRunAPI).toHaveBeenCalledWith('run-1');
    });

    it('does not anonymously re-request after token is cleared', async () => {
        useAuthStore.getState().setToken('tok');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result, rerender } = renderHook(() => useRepoAnalysisRunQuery('run-1'), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });

        mockGetRepoAnalysisRunAPI.mockClear();
        useAuthStore.getState().clearAuth();
        mockUseMeQuery.mockReturnValue(mockMe({
            data: undefined,
            isSuccess: false,
            isPending: true,
            status: 'pending',
        }));
        rerender();

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetRepoAnalysisRunAPI).not.toHaveBeenCalled();
    });
});
