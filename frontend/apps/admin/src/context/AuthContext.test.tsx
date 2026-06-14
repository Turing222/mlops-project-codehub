import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { AuthProvider } from './AuthContext';
import { useAuth } from './useAuth';
import { createTestQueryClient } from '../test/render-with-query';
import { useAuthStore } from '../stores/auth-store';
import { AUTH_UNAUTHORIZED_EVENT } from '../lib/http/auth';
import { authKeys } from '../query/keys/auth';

vi.mock('../query/hooks/auth', () => ({
    useMeQuery: vi.fn(),
}));

import { useMeQuery } from '../query/hooks/auth';

const mockUseMeQuery = vi.mocked(useMeQuery);

type UseQueryResult = ReturnType<typeof useMeQuery>;

function mockMeQuery(overrides: Partial<UseQueryResult> = {}): UseQueryResult {
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
    } as UseQueryResult;
}

function createWrapper(queryClient?: ReturnType<typeof createTestQueryClient>) {
    const qc = queryClient ?? createTestQueryClient();
    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={qc}>
            <AuthProvider>{children}</AuthProvider>
        </QueryClientProvider>
    );
}

beforeEach(() => {
    useAuthStore.getState().resetAll();
});

describe('AuthProvider', () => {
    it('provides user from useMeQuery data', () => {
        mockUseMeQuery.mockReturnValue(mockMeQuery({
            data: { id: '1', username: 'alice' } as UseQueryResult['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        expect(result.current.user).toEqual({ id: '1', username: 'alice' });
        expect(result.current.isAuthenticated).toBe(true);
    });

    it('isAuthenticated is false when no user', () => {
        mockUseMeQuery.mockReturnValue(mockMeQuery({
            isSuccess: false,
            isPending: false,
            status: 'error',
        }));

        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        expect(result.current.isAuthenticated).toBe(false);
    });

    it('isLoading is true only when token exists and query loading', () => {
        useAuthStore.getState().setToken('abc');
        mockUseMeQuery.mockReturnValue(mockMeQuery({
            isLoading: true,
            isPending: true,
            isFetching: true,
            status: 'pending',
            fetchStatus: 'fetching',
        }));

        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        expect(result.current.isLoading).toBe(true);
    });

    it('isLoading is false when no token even if query loading', () => {
        mockUseMeQuery.mockReturnValue(mockMeQuery({
            isLoading: true,
            isPending: true,
            isFetching: true,
            status: 'pending',
            fetchStatus: 'fetching',
        }));

        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        expect(result.current.isLoading).toBe(false);
    });

    it('clears token and removes auth queries on unauthorized event', async () => {
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(authKeys.me(), { id: '1', username: 'alice' });
        useAuthStore.getState().setToken('old-token');

        mockUseMeQuery.mockReturnValue(mockMeQuery({
            data: { id: '1', username: 'alice' } as UseQueryResult['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        renderHook(() => useAuth(), { wrapper: createWrapper(queryClient) });

        window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));

        await waitFor(() => {
            expect(useAuthStore.getState().token).toBeNull();
        });
        expect(queryClient.getQueryData(authKeys.me())).toBeUndefined();
    });

    it('login sets token, refetches, and closes modal on success', async () => {
        const refetch = vi.fn().mockResolvedValue({ data: { id: '1', username: 'alice' }, error: null });
        mockUseMeQuery.mockReturnValue(mockMeQuery({ refetch }));

        useAuthStore.getState().setShowAuthModal(true);
        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        await result.current.login('new-token');

        expect(useAuthStore.getState().token).toBe('new-token');
        expect(refetch).toHaveBeenCalled();
        expect(useAuthStore.getState().showAuthModal).toBe(false);
    });

    it('login clears auth on refetch error', async () => {
        const refetch = vi.fn().mockResolvedValue({
            data: undefined,
            error: new Error('fail'),
        });
        mockUseMeQuery.mockReturnValue(mockMeQuery({ refetch }));

        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        await expect(result.current.login('bad-token')).rejects.toThrow('fail');
        expect(useAuthStore.getState().token).toBeNull();
    });

    it('logout clears auth and clears entire query cache', () => {
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(authKeys.me(), { id: '1' });
        queryClient.setQueryData(['chat', 'sessions'], { items: [] });
        useAuthStore.getState().setToken('token');

        mockUseMeQuery.mockReturnValue(mockMeQuery({
            data: { id: '1', username: 'alice' } as UseQueryResult['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper(queryClient) });

        result.current.logout();

        expect(useAuthStore.getState().token).toBeNull();
        expect(queryClient.getQueryData(authKeys.me())).toBeUndefined();
        expect(queryClient.getQueryData(['chat', 'sessions'])).toBeUndefined();
    });

    it('login function reference is stable across re-renders', () => {
        const refetch = vi.fn().mockResolvedValue({ data: { id: '1' }, error: null });
        mockUseMeQuery.mockReturnValue(mockMeQuery({ refetch }));

        const { result, rerender } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        const firstLoginRef = result.current.login;
        rerender();
        const secondLoginRef = result.current.login;

        expect(firstLoginRef).toBe(secondLoginRef);
    });
});
