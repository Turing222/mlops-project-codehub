import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useMeQuery } from './auth';
import { createTestQueryClient } from '../../test/render-with-query';
import { useAuthStore } from '../../stores/auth-store';

vi.mock('../../api/auth', () => ({
    getUserProfileAPI: vi.fn(),
}));

import { getUserProfileAPI } from '../../api/auth';

const mockGetUserProfileAPI = vi.mocked(getUserProfileAPI);

function createWrapper() {
    const queryClient = createTestQueryClient();
    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
}

beforeEach(() => {
    useAuthStore.getState().resetAll();
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

        // After token cleared, query should be disabled — no new fetch
        expect(result.current.fetchStatus).toBe('idle');
    });
});
