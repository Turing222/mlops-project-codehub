import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import {
    useDefaultKBQuery,
    useDeleteKBFileMutation,
    useKBFilesQuery,
} from './knowledge';
import { createTestQueryClient } from '../../test/render-with-query';
import { knowledgeKeys } from '../keys/knowledge';
import { useAuthStore } from '../../stores/auth-store';

vi.mock('../../api/knowledge', () => ({
    getDefaultKBAPI: vi.fn(),
    getDefaultKBFilesAPI: vi.fn(),
    deleteKBFileAPI: vi.fn(),
}));

vi.mock('./auth', () => ({
    useMeQuery: vi.fn(),
}));

import {
    deleteKBFileAPI,
    getDefaultKBAPI,
    getDefaultKBFilesAPI,
} from '../../api/knowledge';
import { useMeQuery } from './auth';

const mockGetDefaultKBAPI = vi.mocked(getDefaultKBAPI);
const mockGetDefaultKBFilesAPI = vi.mocked(getDefaultKBFilesAPI);
const mockDeleteKBFileAPI = vi.mocked(deleteKBFileAPI);
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

function createWrapper(queryClient?: ReturnType<typeof createTestQueryClient>) {
    const qc = queryClient ?? createTestQueryClient();
    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
}

const defaultKb = { id: 'kb1', name: 'Default KB' };
const files = [
    {
        id: 'f1',
        kb_id: 'kb1',
        filename: 'doc.md',
        file_size: 128,
        status: 'READY',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    },
];

function authedMe() {
    mockUseMeQuery.mockReturnValue(mockMe({
        data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
        isSuccess: true,
        isPending: false,
        status: 'success',
    }));
    useAuthStore.getState().setToken('tok');
}

beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.getState().resetAll();
    mockUseMeQuery.mockReturnValue(mockMe());
    mockGetDefaultKBAPI.mockResolvedValue(defaultKb);
    mockGetDefaultKBFilesAPI.mockResolvedValue(files);
    mockDeleteKBFileAPI.mockResolvedValue(undefined);
});

describe('useDefaultKBQuery', () => {
    it('does not auto-request when enabled is false', () => {
        authedMe();
        const { result } = renderHook(() => useDefaultKBQuery({ enabled: false }), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetDefaultKBAPI).not.toHaveBeenCalled();
    });

    it('does not request when unauthenticated even if enabled is true', () => {
        const { result } = renderHook(() => useDefaultKBQuery({ enabled: true }), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetDefaultKBAPI).not.toHaveBeenCalled();
    });

    it('can resolve and cache default KB via fetchQuery when observer is disabled', async () => {
        authedMe();
        const queryClient = createTestQueryClient();
        const { result } = renderHook(() => useDefaultKBQuery({ enabled: false }), {
            wrapper: createWrapper(queryClient),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetDefaultKBAPI).not.toHaveBeenCalled();

        await act(async () => {
            const { defaultKBQueryOptions } = await import('./knowledge');
            await queryClient.fetchQuery(defaultKBQueryOptions());
        });

        await waitFor(() => {
            expect(result.current.data).toEqual(defaultKb);
        });
        expect(mockGetDefaultKBAPI).toHaveBeenCalledTimes(1);
    });
});

describe('useKBFilesQuery', () => {
    it('does not request when enabled is false', () => {
        authedMe();
        const { result } = renderHook(() => useKBFilesQuery({ enabled: false }), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetDefaultKBFilesAPI).not.toHaveBeenCalled();
    });

    it('does not request when token or bootstrap user is missing', () => {
        useAuthStore.getState().setToken('tok');
        mockUseMeQuery.mockReturnValue(mockMe({
            isSuccess: false,
            isPending: false,
            status: 'error',
        }));

        const { result } = renderHook(() => useKBFilesQuery({ enabled: true }), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetDefaultKBFilesAPI).not.toHaveBeenCalled();
    });

    it('fetches file list when authenticated and enabled is true', async () => {
        authedMe();
        const { result } = renderHook(() => useKBFilesQuery({ enabled: true }), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });
        expect(result.current.data).toEqual(files);
        expect(mockGetDefaultKBFilesAPI).toHaveBeenCalledTimes(1);
    });

    it('stops requesting after logout while still enabled=true (modal left open)', async () => {
        authedMe();
        const { result, rerender } = renderHook(
            ({ enabled }) => useKBFilesQuery({ enabled }),
            {
                wrapper: createWrapper(),
                initialProps: { enabled: true },
            },
        );

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });

        mockGetDefaultKBFilesAPI.mockClear();
        useAuthStore.getState().clearAuth();
        mockUseMeQuery.mockReturnValue(mockMe({
            data: undefined,
            isSuccess: false,
            isPending: true,
            status: 'pending',
        }));
        rerender({ enabled: true });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetDefaultKBFilesAPI).not.toHaveBeenCalled();
    });
});

describe('useDeleteKBFileMutation', () => {
    it('invalidates files key on success when identity is stable', async () => {
        useAuthStore.getState().setToken('tok');
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(knowledgeKeys.files(), files);
        const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

        const { result } = renderHook(() => useDeleteKBFileMutation(), {
            wrapper: createWrapper(queryClient),
        });

        await act(async () => {
            await result.current.mutateAsync('f1');
        });

        expect(mockDeleteKBFileAPI).toHaveBeenCalledWith('f1');
        expect(invalidateSpy).toHaveBeenCalledWith({
            queryKey: knowledgeKeys.files(),
        });
    });

    it('does not fabricate success data on failure', async () => {
        mockDeleteKBFileAPI.mockRejectedValue(new Error('delete failed'));
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(knowledgeKeys.files(), files);

        const { result } = renderHook(() => useDeleteKBFileMutation(), {
            wrapper: createWrapper(queryClient),
        });

        await expect(
            act(async () => {
                await result.current.mutateAsync('f1');
            }),
        ).rejects.toThrow('delete failed');

        expect(queryClient.getQueryData(knowledgeKeys.files())).toEqual(files);
    });
});
