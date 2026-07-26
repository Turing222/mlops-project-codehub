import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import {
    useDefaultKBQuery,
    useDeleteKBFileMutation,
    useKBFilesQuery,
    useKBTaskStatusQuery,
    useUploadKBFileMutation,
} from './knowledge';
import { createTestQueryClient } from '../../test/render-with-query';
import { knowledgeKeys } from '../keys/knowledge';
import { useAuthStore } from '../../stores/auth-store';

vi.mock('../../api/knowledge', () => ({
    getDefaultKBAPI: vi.fn(),
    getDefaultKBFilesAPI: vi.fn(),
    deleteKBFileAPI: vi.fn(),
    uploadKBFileAPI: vi.fn(),
    getKBTaskStatusAPI: vi.fn(),
}));

vi.mock('./auth', () => ({
    useMeQuery: vi.fn(),
}));

import {
    deleteKBFileAPI,
    getDefaultKBAPI,
    getDefaultKBFilesAPI,
    getKBTaskStatusAPI,
    uploadKBFileAPI,
} from '../../api/knowledge';
import { useMeQuery } from './auth';

const mockGetDefaultKBAPI = vi.mocked(getDefaultKBAPI);
const mockGetDefaultKBFilesAPI = vi.mocked(getDefaultKBFilesAPI);
const mockDeleteKBFileAPI = vi.mocked(deleteKBFileAPI);
const mockUploadKBFileAPI = vi.mocked(uploadKBFileAPI);
const mockGetKBTaskStatusAPI = vi.mocked(getKBTaskStatusAPI);
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

const pendingTask = {
    id: 'task-1',
    action_type: 'ingest',
    status: 'running',
    progress: 10,
    payload: { file_status: 'PARSING' },
    error_log: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
};

beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.getState().resetAll();
    mockUseMeQuery.mockReturnValue(mockMe());
    mockGetDefaultKBAPI.mockResolvedValue(defaultKb);
    mockGetDefaultKBFilesAPI.mockResolvedValue(files);
    mockDeleteKBFileAPI.mockResolvedValue(undefined);
    mockUploadKBFileAPI.mockResolvedValue({
        task_id: 'task-1',
        file_id: 'file-1',
        file_status: 'PENDING',
        task_status: 'pending',
        deduplicated: false,
    });
    mockGetKBTaskStatusAPI.mockResolvedValue(pendingTask);
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

describe('useUploadKBFileMutation', () => {
    it('calls upload API with retry disabled', async () => {
        const file = new File(['# hi'], 'doc.md', { type: 'text/markdown' });
        const { result } = renderHook(() => useUploadKBFileMutation(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            await result.current.mutateAsync(file);
        });

        expect(mockUploadKBFileAPI).toHaveBeenCalledWith(file);
        expect(result.current.failureCount).toBe(0);
    });

    it('does not auto-retry on failure', async () => {
        mockUploadKBFileAPI.mockRejectedValue(new Error('upload failed'));
        const file = new File(['# hi'], 'doc.md', { type: 'text/markdown' });
        const { result } = renderHook(() => useUploadKBFileMutation(), {
            wrapper: createWrapper(),
        });

        await expect(
            act(async () => {
                await result.current.mutateAsync(file);
            }),
        ).rejects.toThrow('upload failed');

        expect(mockUploadKBFileAPI).toHaveBeenCalledTimes(1);
    });
});

describe('useKBTaskStatusQuery', () => {
    it('does not query when task id is empty or disabled', () => {
        authedMe();
        const { result: emptyId } = renderHook(
            () => useKBTaskStatusQuery('', { enabled: true }),
            { wrapper: createWrapper() },
        );
        const { result: disabled } = renderHook(
            () => useKBTaskStatusQuery('task-1', { enabled: false }),
            { wrapper: createWrapper() },
        );

        expect(emptyId.current.fetchStatus).toBe('idle');
        expect(disabled.current.fetchStatus).toBe('idle');
        expect(mockGetKBTaskStatusAPI).not.toHaveBeenCalled();
    });

    it('polls every second while task is active', async () => {
        vi.useFakeTimers();
        authedMe();
        mockGetKBTaskStatusAPI.mockResolvedValue(pendingTask);

        const { result } = renderHook(
            () => useKBTaskStatusQuery('task-1', { enabled: true }),
            { wrapper: createWrapper() },
        );

        await act(async () => {
            await vi.advanceTimersByTimeAsync(0);
        });
        await act(async () => {
            await Promise.resolve();
        });

        expect(mockGetKBTaskStatusAPI).toHaveBeenCalled();
        const callsAfterFirst = mockGetKBTaskStatusAPI.mock.calls.length;

        await act(async () => {
            await vi.advanceTimersByTimeAsync(1000);
        });
        await act(async () => {
            await Promise.resolve();
        });

        expect(mockGetKBTaskStatusAPI.mock.calls.length).toBeGreaterThan(callsAfterFirst);
        expect(result.current.data?.status).toBe('running');
        vi.useRealTimers();
    });

    it.each([
        {
            status: 'completed',
            taskId: 'task-done',
            progress: 100,
            payload: { file_status: 'READY' },
        },
        {
            status: 'failed',
            taskId: 'task-failed',
            progress: 40,
            payload: { file_status: 'FAILED' },
        },
    ] as const)('stops interval when status is $status', async ({ status, taskId, progress, payload }) => {
        vi.useFakeTimers();
        authedMe();
        mockGetKBTaskStatusAPI.mockResolvedValue({
            ...pendingTask,
            id: taskId,
            status,
            progress,
            payload,
            error_log: status === 'failed' ? 'failed' : null,
        });

        renderHook(
            () => useKBTaskStatusQuery(taskId, { enabled: true }),
            { wrapper: createWrapper() },
        );

        await act(async () => {
            await vi.advanceTimersByTimeAsync(0);
        });
        await act(async () => {
            await Promise.resolve();
        });
        const callsAfterTerminal = mockGetKBTaskStatusAPI.mock.calls.length;

        await act(async () => {
            await vi.advanceTimersByTimeAsync(3000);
        });

        expect(mockGetKBTaskStatusAPI).toHaveBeenCalledTimes(callsAfterTerminal);
        vi.useRealTimers();
    });

    it('does not stack Query retries on a single query error', async () => {
        authedMe();
        mockGetKBTaskStatusAPI.mockRejectedValue(new Error('network blip'));

        const { result } = renderHook(
            () => useKBTaskStatusQuery('task-err', { enabled: true }),
            { wrapper: createWrapper() },
        );

        await waitFor(() => {
            expect(result.current.isError).toBe(true);
        });

        expect(mockGetKBTaskStatusAPI).toHaveBeenCalledTimes(1);
    });
});
