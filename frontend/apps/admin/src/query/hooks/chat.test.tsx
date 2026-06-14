import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useChatSessionsQuery, useSessionDetailQuery } from './chat';
import { createTestQueryClient } from '../../test/render-with-query';
import { useAuthStore } from '../../stores/auth-store';

vi.mock('../../api/chat', () => ({
    getSessionsAPI: vi.fn(),
    getSessionDetailAPI: vi.fn(),
}));

vi.mock('./auth', () => ({
    useMeQuery: vi.fn(),
}));

import { getSessionsAPI, getSessionDetailAPI } from '../../api/chat';
import { useMeQuery } from './auth';

const mockGetSessionsAPI = vi.mocked(getSessionsAPI);
const mockGetSessionDetailAPI = vi.mocked(getSessionDetailAPI);
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

const sessionListData = {
    items: [{ id: 's1', title: 'Hello', user_id: 'u1', created_at: '', updated_at: '' }],
    total: 1,
    skip: 0,
    limit: 50,
};

beforeEach(() => {
    useAuthStore.getState().resetAll();
    mockGetSessionsAPI.mockResolvedValue(sessionListData);
    mockGetSessionDetailAPI.mockResolvedValue({
        session: { id: 's1', title: 'Hello', user_id: 'u1', created_at: '', updated_at: '' },
        messages: [],
        total_messages: 0,
    });
});

describe('useChatSessionsQuery', () => {
    it('is disabled when no token', () => {
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(() => useChatSessionsQuery(), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetSessionsAPI).not.toHaveBeenCalled();
    });

    it('is disabled when no user', () => {
        useAuthStore.getState().setToken('abc');
        mockUseMeQuery.mockReturnValue(mockMe({
            isSuccess: false,
            isPending: false,
            status: 'error',
        }));

        const { result } = renderHook(() => useChatSessionsQuery(), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetSessionsAPI).not.toHaveBeenCalled();
    });

    it('is enabled when both token and user exist', async () => {
        useAuthStore.getState().setToken('abc');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(() => useChatSessionsQuery(), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });
        expect(mockGetSessionsAPI).toHaveBeenCalled();
    });
});

describe('useSessionDetailQuery', () => {
    it('is disabled when sessionId is null', () => {
        useAuthStore.getState().setToken('abc');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(() => useSessionDetailQuery(null), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetSessionDetailAPI).not.toHaveBeenCalled();
    });

    it('is enabled when sessionId, token, and user exist', async () => {
        useAuthStore.getState().setToken('abc');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(() => useSessionDetailQuery('s1'), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });
        expect(mockGetSessionDetailAPI).toHaveBeenCalledWith('s1', 0, 100);
    });

    it('passes custom skip and limit to API', async () => {
        useAuthStore.getState().setToken('abc');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(() => useSessionDetailQuery('s1', 10, 50), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });
        expect(mockGetSessionDetailAPI).toHaveBeenCalledWith('s1', 10, 50);
    });
});
