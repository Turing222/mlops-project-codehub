import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { AuthProvider } from './AuthContext';
import { useAuth } from './useAuth';
import { createTestQueryClient } from '../test/render-with-query';
import { useAuthStore } from '../stores/auth-store';
import { AUTH_UNAUTHORIZED_EVENT } from '../lib/http/auth';
import { authKeys } from '../query/keys/auth';
import { chatKeys } from '../query/keys/chat';

vi.mock('../api/auth', () => ({
    getUserProfileAPI: vi.fn(),
    updateUserProfileAPI: vi.fn(),
}));

import { getUserProfileAPI } from '../api/auth';

const mockGetUserProfileAPI = vi.mocked(getUserProfileAPI);

const userA = { id: 'a', username: 'alice' };
const userB = { id: 'b', username: 'bob' };

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
    vi.clearAllMocks();
    mockGetUserProfileAPI.mockResolvedValue(userA);
});

describe('AuthProvider', () => {
    it('provides user from /users/me when token is set', async () => {
        useAuthStore.getState().setToken('tok-a');

        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        await waitFor(() => {
            expect(result.current.user).toEqual(userA);
        });
        expect(result.current.isAuthenticated).toBe(true);
    });

    it('isAuthenticated is false when no user', async () => {
        useAuthStore.getState().setToken('tok');
        mockGetUserProfileAPI.mockRejectedValue(new Error('fail'));

        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
        });
        expect(result.current.isAuthenticated).toBe(false);
        expect(result.current.user).toBeNull();
    });

    it('isLoading is true only when token exists and query loading', async () => {
        let resolveProfile: (value: typeof userA) => void = () => undefined;
        mockGetUserProfileAPI.mockImplementation(
            () => new Promise((resolve) => {
                resolveProfile = resolve;
            }),
        );
        useAuthStore.getState().setToken('abc');

        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        await waitFor(() => {
            expect(result.current.isLoading).toBe(true);
        });

        await act(async () => {
            resolveProfile(userA);
        });

        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
        });
    });

    it('isLoading is false when no token even if query would load', () => {
        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        expect(result.current.isLoading).toBe(false);
        expect(mockGetUserProfileAPI).not.toHaveBeenCalled();
    });

    it('logout clears token synchronously before async cache clear', async () => {
        useAuthStore.getState().setToken('tok-a');
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(authKeys.me(), userA);
        queryClient.setQueryData(chatKeys.sessions(), { items: [] });

        const { result } = renderHook(() => useAuth(), {
            wrapper: createWrapper(queryClient),
        });

        await waitFor(() => {
            expect(result.current.isAuthenticated).toBe(true);
        });

        // Intentionally no await: clearAuth must run before logout() returns.
        result.current.logout();
        expect(useAuthStore.getState().token).toBeNull();

        await act(async () => {
            // Flush React re-render + async cancel/clear.
            await Promise.resolve();
        });

        expect(result.current.user).toBeNull();
        expect(result.current.isAuthenticated).toBe(false);
        await waitFor(() => {
            expect(queryClient.getQueryData(authKeys.me())).toBeUndefined();
            expect(queryClient.getQueryData(chatKeys.sessions())).toBeUndefined();
        });
    });

    it('logout clears token and entire query cache including chat', async () => {
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(authKeys.me(), userA);
        queryClient.setQueryData(chatKeys.sessions(), { items: [] });
        useAuthStore.getState().setToken('token');

        const { result } = renderHook(() => useAuth(), {
            wrapper: createWrapper(queryClient),
        });

        result.current.logout();
        expect(useAuthStore.getState().token).toBeNull();

        await waitFor(() => {
            expect(queryClient.getQueryData(authKeys.me())).toBeUndefined();
            expect(queryClient.getQueryData(chatKeys.sessions())).toBeUndefined();
        });
    });

    it('logout force-clears even when token already empty', async () => {
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(authKeys.me(), userA);
        queryClient.setQueryData(chatKeys.sessions(), { items: [] });

        const { result } = renderHook(() => useAuth(), {
            wrapper: createWrapper(queryClient),
        });

        await act(async () => {
            result.current.logout();
        });

        await waitFor(() => {
            expect(queryClient.getQueryData(authKeys.me())).toBeUndefined();
            expect(queryClient.getQueryData(chatKeys.sessions())).toBeUndefined();
        });
    });

    it('unauthorized event clears token and entire query cache', async () => {
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(authKeys.me(), userA);
        queryClient.setQueryData(chatKeys.sessions(), { items: [] });
        useAuthStore.getState().setToken('old-token');

        renderHook(() => useAuth(), { wrapper: createWrapper(queryClient) });

        await act(async () => {
            window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
        });

        await waitFor(() => {
            expect(useAuthStore.getState().token).toBeNull();
            expect(queryClient.getQueryData(authKeys.me())).toBeUndefined();
            expect(queryClient.getQueryData(chatKeys.sessions())).toBeUndefined();
        });
    });

    it('repeated unauthorized events no-op after token is cleared (single cancel/clear)', async () => {
        const queryClient = createTestQueryClient();
        const cancelSpy = vi.spyOn(queryClient, 'cancelQueries');
        const clearSpy = vi.spyOn(queryClient, 'clear');
        useAuthStore.getState().setToken('old-token');
        queryClient.setQueryData(authKeys.me(), userA);

        renderHook(() => useAuth(), { wrapper: createWrapper(queryClient) });

        await act(async () => {
            window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
            window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
            window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
        });

        await waitFor(() => {
            expect(useAuthStore.getState().token).toBeNull();
        });

        // First event runs terminate; subsequent events see empty token and no-op.
        expect(cancelSpy).toHaveBeenCalledTimes(1);
        expect(clearSpy).toHaveBeenCalledTimes(1);
    });

    it('delayed A query result does not repopulate cache after identity terminate', async () => {
        const queryClient = createTestQueryClient();
        let resolveProfile: (value: typeof userA) => void = () => undefined;
        mockGetUserProfileAPI.mockImplementation(
            () => new Promise((resolve) => {
                resolveProfile = resolve;
            }),
        );
        useAuthStore.getState().setToken('tok-a');

        const { result } = renderHook(() => useAuth(), {
            wrapper: createWrapper(queryClient),
        });

        await waitFor(() => {
            expect(mockGetUserProfileAPI).toHaveBeenCalled();
        });

        await act(async () => {
            result.current.logout();
        });

        await waitFor(() => {
            expect(useAuthStore.getState().token).toBeNull();
            expect(queryClient.getQueryData(authKeys.me())).toBeUndefined();
        });

        await act(async () => {
            resolveProfile(userA);
            await Promise.resolve();
            await Promise.resolve();
        });

        expect(queryClient.getQueryData(authKeys.me())).toBeUndefined();
    });

    it('login sets token, bootstraps /me via shared options, and closes modal on success', async () => {
        mockGetUserProfileAPI.mockResolvedValue(userA);
        useAuthStore.getState().setShowAuthModal(true);
        const { result } = renderHook(() => useAuth(), { wrapper: createWrapper() });

        await act(async () => {
            await result.current.login('new-token');
        });

        expect(useAuthStore.getState().token).toBe('new-token');
        expect(mockGetUserProfileAPI).toHaveBeenCalled();
        expect(useAuthStore.getState().showAuthModal).toBe(false);
        await waitFor(() => {
            expect(result.current.user).toEqual(userA);
            expect(result.current.isAuthenticated).toBe(true);
        });
    });

    it('login bootstrap failure runs full identity terminate and rethrows', async () => {
        mockGetUserProfileAPI.mockRejectedValue(new Error('bootstrap fail'));
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(chatKeys.sessions(), { items: [] });

        const { result } = renderHook(() => useAuth(), {
            wrapper: createWrapper(queryClient),
        });

        await expect(
            act(async () => {
                await result.current.login('bad-token');
            }),
        ).rejects.toThrow('bootstrap fail');

        expect(useAuthStore.getState().token).toBeNull();
        await waitFor(() => {
            expect(queryClient.getQueryData(chatKeys.sessions())).toBeUndefined();
        });
    });

    it('login(B) while authenticated as A clears A cache then bootstraps B', async () => {
        const queryClient = createTestQueryClient();
        useAuthStore.getState().setToken('tok-a');
        mockGetUserProfileAPI.mockResolvedValueOnce(userA);

        const { result } = renderHook(() => useAuth(), {
            wrapper: createWrapper(queryClient),
        });

        await waitFor(() => {
            expect(result.current.user).toEqual(userA);
        });

        queryClient.setQueryData(chatKeys.sessions(), { items: [{ id: 'a-session' }] });
        queryClient.setQueryData(['credits'], { balance: 99 });

        mockGetUserProfileAPI.mockResolvedValueOnce(userB);

        await act(async () => {
            await result.current.login('tok-b');
        });

        expect(useAuthStore.getState().token).toBe('tok-b');
        expect(queryClient.getQueryData(chatKeys.sessions())).toBeUndefined();
        expect(queryClient.getQueryData(['credits'])).toBeUndefined();
        await waitFor(() => {
            expect(result.current.user).toEqual(userB);
            expect(queryClient.getQueryData(authKeys.me())).toEqual(userB);
        });
    });

    it('login function reference is stable across re-renders when me user is stable', async () => {
        useAuthStore.getState().setToken('tok');
        mockGetUserProfileAPI.mockResolvedValue(userA);

        const { result, rerender } = renderHook(() => useAuth(), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.user).toEqual(userA);
        });

        const firstLoginRef = result.current.login;
        rerender();
        expect(result.current.login).toBe(firstLoginRef);
    });

    it('persisted-token bootstrap non-401 failure clears token and cache', async () => {
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(chatKeys.sessions(), { items: [] });
        useAuthStore.getState().setToken('persisted-token');
        mockGetUserProfileAPI.mockRejectedValue(new Error('network down'));

        renderHook(() => useAuth(), { wrapper: createWrapper(queryClient) });

        await waitFor(() => {
            expect(useAuthStore.getState().token).toBeNull();
            expect(queryClient.getQueryData(chatKeys.sessions())).toBeUndefined();
        });
    });

    it('background /me refetch 500 after successful bootstrap does not log out', async () => {
        const queryClient = createTestQueryClient();
        useAuthStore.getState().setToken('tok-a');
        mockGetUserProfileAPI.mockResolvedValueOnce(userA);

        const { result } = renderHook(() => useAuth(), {
            wrapper: createWrapper(queryClient),
        });

        await waitFor(() => {
            expect(result.current.isAuthenticated).toBe(true);
            expect(result.current.user).toEqual(userA);
        });

        mockGetUserProfileAPI.mockRejectedValueOnce(new Error('server 500'));
        await act(async () => {
            await result.current.refreshUser().catch(() => undefined);
        });

        // Refetch error must not tear down a previously confirmed identity.
        expect(useAuthStore.getState().token).toBe('tok-a');
        expect(result.current.isAuthenticated).toBe(true);
        expect(result.current.user).toEqual(userA);
    });

    it('delayed A unauthorized does not log out already-logged-in B', async () => {
        const queryClient = createTestQueryClient();
        mockGetUserProfileAPI.mockResolvedValueOnce(userA);

        const { result } = renderHook(() => useAuth(), {
            wrapper: createWrapper(queryClient),
        });

        await act(async () => {
            await result.current.login('tok-a');
        });
        await waitFor(() => {
            expect(result.current.user).toEqual(userA);
        });

        mockGetUserProfileAPI.mockResolvedValueOnce(userB);
        await act(async () => {
            await result.current.login('tok-b');
        });
        await waitFor(() => {
            expect(result.current.user).toEqual(userB);
            expect(useAuthStore.getState().token).toBe('tok-b');
        });

        await act(async () => {
            window.dispatchEvent(
                new CustomEvent(AUTH_UNAUTHORIZED_EVENT, {
                    detail: { token: 'tok-a' },
                }),
            );
            await Promise.resolve();
        });

        expect(useAuthStore.getState().token).toBe('tok-b');
        expect(result.current.user).toEqual(userB);
        expect(result.current.isAuthenticated).toBe(true);
    });

    it('unauthorized for current token still terminates B', async () => {
        useAuthStore.getState().setToken('tok-b');
        mockGetUserProfileAPI.mockResolvedValue(userB);
        const queryClient = createTestQueryClient();

        const { result } = renderHook(() => useAuth(), {
            wrapper: createWrapper(queryClient),
        });

        await waitFor(() => {
            expect(result.current.isAuthenticated).toBe(true);
        });

        await act(async () => {
            window.dispatchEvent(
                new CustomEvent(AUTH_UNAUTHORIZED_EVENT, {
                    detail: { token: 'tok-b' },
                }),
            );
        });

        await waitFor(() => {
            expect(useAuthStore.getState().token).toBeNull();
            expect(result.current.isAuthenticated).toBe(false);
        });
    });
});
