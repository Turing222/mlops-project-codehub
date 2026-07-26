import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useMeQuery, useUpdateProfileMutation } from './auth';
import { createTestQueryClient } from '../../test/render-with-query';
import { useAuthStore } from '../../stores/auth-store';
import { authKeys } from '../keys/auth';

function createStickyQueryClient() {
    return new QueryClient({
        defaultOptions: {
            queries: { retry: false, gcTime: Infinity },
            mutations: { retry: false },
        },
    });
}

vi.mock('../../api/auth', () => ({
    getUserProfileAPI: vi.fn(),
    updateUserProfileAPI: vi.fn(),
}));

import { getUserProfileAPI, updateUserProfileAPI } from '../../api/auth';

const mockGetUserProfileAPI = vi.mocked(getUserProfileAPI);
const mockUpdateUserProfileAPI = vi.mocked(updateUserProfileAPI);

function createWrapper(queryClient?: ReturnType<typeof createTestQueryClient>) {
    const client = queryClient ?? createTestQueryClient();
    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
}

beforeEach(() => {
    useAuthStore.getState().resetAll();
    vi.clearAllMocks();
});

describe('useMeQuery', () => {
    it('is disabled when no token', () => {
        useAuthStore.getState().resetAll();
        mockGetUserProfileAPI.mockResolvedValue({ id: '1', username: 'alice' });

        const { result } = renderHook(() => useMeQuery(), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockGetUserProfileAPI).not.toHaveBeenCalled();
    });

    it('is enabled when token exists', async () => {
        useAuthStore.getState().setToken('abc');
        mockGetUserProfileAPI.mockResolvedValue({ id: '1', username: 'alice' });

        const { result } = renderHook(() => useMeQuery(), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });
        expect(mockGetUserProfileAPI).toHaveBeenCalled();
    });

    it('returns user data on success', async () => {
        const user = { id: '1', username: 'alice' };
        useAuthStore.getState().setToken('abc');
        mockGetUserProfileAPI.mockResolvedValue(user);

        const { result } = renderHook(() => useMeQuery(), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.data).toEqual(user);
        });
    });

    it('does not fetch after token cleared', async () => {
        useAuthStore.getState().setToken('abc');
        mockGetUserProfileAPI.mockResolvedValue({ id: '1', username: 'alice' });

        const { result, rerender } = renderHook(() => useMeQuery(), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });

        useAuthStore.getState().clearAuth();
        mockGetUserProfileAPI.mockClear();
        rerender();

        expect(result.current.fetchStatus).toBe('idle');
    });
});

describe('useUpdateProfileMutation', () => {
    it('does not overwrite /me when identity changed before delayed success', async () => {
        // Keep cache resident (default test client uses gcTime: 0).
        const queryClient = createStickyQueryClient();
        const userB = { id: 'b', username: 'bob' };
        queryClient.setQueryData(authKeys.me(), userB);

        let resolveUpdate!: (value: { id: string; username: string }) => void;
        mockUpdateUserProfileAPI.mockImplementation(
            () => new Promise((resolve) => {
                resolveUpdate = resolve;
            }),
        );

        useAuthStore.getState().setToken('tok-a');
        const { result } = renderHook(() => useUpdateProfileMutation(), {
            wrapper: createWrapper(queryClient),
        });

        let mutationPromise!: Promise<unknown>;
        await act(async () => {
            mutationPromise = result.current.mutateAsync({ username: 'alice-new' });
        });

        await waitFor(() => {
            expect(mockUpdateUserProfileAPI).toHaveBeenCalled();
        });

        // Identity replace A → B while profile update for A is still in flight.
        useAuthStore.getState().setToken('tok-b');

        await act(async () => {
            resolveUpdate({ id: 'a', username: 'alice-new' });
            await mutationPromise;
        });

        expect(queryClient.getQueryData(authKeys.me())).toEqual(userB);
        expect(queryClient.getQueryData(authKeys.me())).not.toEqual({
            id: 'a',
            username: 'alice-new',
        });
    });

    it('writes /me when identity is still the same', async () => {
        const queryClient = createStickyQueryClient();
        useAuthStore.getState().setToken('tok-a');
        mockUpdateUserProfileAPI.mockResolvedValue({ id: 'a', username: 'alice-new' });
        // invalidateQueries may refetch /me — keep it resolved.
        mockGetUserProfileAPI.mockResolvedValue({ id: 'a', username: 'alice-new' });

        const { result } = renderHook(() => useUpdateProfileMutation(), {
            wrapper: createWrapper(queryClient),
        });

        await act(async () => {
            await result.current.mutateAsync({ username: 'alice-new' });
        });

        expect(queryClient.getQueryData(authKeys.me())).toEqual({
            id: 'a',
            username: 'alice-new',
        });
    });
});
