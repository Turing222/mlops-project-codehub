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

vi.mock('../../api/users', () => ({
    queryUserAPI: vi.fn(),
    updateUserAPI: vi.fn(),
    registerUserAPI: vi.fn(),
    uploadUsersCSVAPI: vi.fn(),
}));

import { queryUserAPI, updateUserAPI, registerUserAPI } from '../../api/users';

const mockQueryUserAPI = vi.mocked(queryUserAPI);
const mockUpdateUserAPI = vi.mocked(updateUserAPI);
const mockRegisterUserAPI = vi.mocked(registerUserAPI);

function createWrapper(queryClient?: ReturnType<typeof createTestQueryClient>) {
    const qc = queryClient ?? createTestQueryClient();
    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
}

beforeEach(() => {
    vi.restoreAllMocks();
});

describe('useUserSearchQuery', () => {
    it('is disabled when no params', () => {
        const { result } = renderHook(() => useUserSearchQuery({}), {
            wrapper: createWrapper(),
        });

        expect(result.current.fetchStatus).toBe('idle');
        expect(mockQueryUserAPI).not.toHaveBeenCalled();
    });

    it('is enabled when username provided', async () => {
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

    it('is enabled when email provided', async () => {
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
