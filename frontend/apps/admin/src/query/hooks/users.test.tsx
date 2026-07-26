import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import {
    useUserSearchQuery,
    useUpdateUserMutation,
    useRegisterUserMutation,
} from './users';
import { createTestQueryClient } from '../../test/render-with-query';
import { userKeys } from '../keys/users';
import { useAuthStore } from '../../stores/auth-store';

vi.mock('../../api/users', () => ({
    queryUserAPI: vi.fn(),
    updateUserAPI: vi.fn(),
    registerUserAPI: vi.fn(),
    uploadUsersCSVAPI: vi.fn(),
}));

vi.mock('./auth', () => ({
    useMeQuery: vi.fn(),
}));

import { queryUserAPI, updateUserAPI, registerUserAPI } from '../../api/users';
import { useMeQuery } from './auth';

const mockQueryUserAPI = vi.mocked(queryUserAPI);
const mockUpdateUserAPI = vi.mocked(updateUserAPI);
const mockRegisterUserAPI = vi.mocked(registerUserAPI);
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

beforeEach(() => {
    vi.restoreAllMocks();
    useAuthStore.getState().resetAll();
    mockUseMeQuery.mockReturnValue(mockMe());
});

describe('useUserSearchQuery', () => {
    it('is disabled when no params', () => {
        useAuthStore.getState().setToken('tok');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(() => useUserSearchQuery({}), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockQueryUserAPI).not.toHaveBeenCalled();
    });

    it('is disabled when token is missing even if params and user exist', () => {
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        const { result } = renderHook(
            () => useUserSearchQuery({ username: 'alice' }),
            { wrapper: createWrapper() },
        );

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockQueryUserAPI).not.toHaveBeenCalled();
    });

    it('is disabled when bootstrap user is missing even if token and params exist', () => {
        useAuthStore.getState().setToken('tok');
        mockUseMeQuery.mockReturnValue(mockMe({
            isSuccess: false,
            isPending: false,
            status: 'error',
        }));

        const { result } = renderHook(
            () => useUserSearchQuery({ username: 'alice' }),
            { wrapper: createWrapper() },
        );

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockQueryUserAPI).not.toHaveBeenCalled();
    });

    it('is enabled when token, user, and username are present', async () => {
        useAuthStore.getState().setToken('tok');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));
        mockQueryUserAPI.mockResolvedValue({ id: '1', username: 'alice' });

        const { result } = renderHook(
            () => useUserSearchQuery({ username: 'alice' }),
            { wrapper: createWrapper() },
        );

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });
        expect(mockQueryUserAPI).toHaveBeenCalledWith({ username: 'alice' });
    });

    it('is enabled when token, user, and email are present', async () => {
        useAuthStore.getState().setToken('tok');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));
        mockQueryUserAPI.mockResolvedValue({ id: '1', username: 'alice' });

        const { result } = renderHook(
            () => useUserSearchQuery({ email: 'a@b.com' }),
            { wrapper: createWrapper() },
        );

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });
        expect(mockQueryUserAPI).toHaveBeenCalledWith({ email: 'a@b.com' });
    });

    it('does not anonymously re-request after token is cleared', async () => {
        useAuthStore.getState().setToken('tok');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));
        mockQueryUserAPI.mockResolvedValue({ id: '1', username: 'alice' });

        const { result, rerender } = renderHook(
            () => useUserSearchQuery({ username: 'alice' }),
            { wrapper: createWrapper() },
        );

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });

        mockQueryUserAPI.mockClear();
        useAuthStore.getState().clearAuth();
        mockUseMeQuery.mockReturnValue(mockMe({
            data: undefined,
            isSuccess: false,
            isPending: true,
            status: 'pending',
        }));
        rerender();

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockQueryUserAPI).not.toHaveBeenCalled();
    });
});

describe('useUpdateUserMutation', () => {
    it('invalidates userKeys.all on success', async () => {
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(userKeys.query({ username: 'test' }), {
            id: '1',
            username: 'test',
        });
        const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

        mockUpdateUserAPI.mockResolvedValue({ id: '1', username: 'updated' });

        const { result } = renderHook(() => useUpdateUserMutation(), {
            wrapper: createWrapper(queryClient),
        });

        await act(async () => {
            result.current.mutate({ id: '1', data: { username: 'updated' } });
        });

        await waitFor(() => {
            expect(invalidateSpy).toHaveBeenCalledWith({
                queryKey: userKeys.all(),
            });
        });
    });
});

describe('useRegisterUserMutation', () => {
    it('does not retry on failure', async () => {
        mockRegisterUserAPI.mockRejectedValue(new Error('register failed'));

        const { result } = renderHook(() => useRegisterUserMutation(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.mutate({
                username: 'alice',
                email: 'a@b.com',
                password: 'password123',
                confirm_password: 'password123',
            });
        });

        await waitFor(() => {
            expect(result.current.isError).toBe(true);
        });
        expect(mockRegisterUserAPI).toHaveBeenCalledOnce();
    });
});
