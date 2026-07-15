import { describe, expect, it, beforeEach, vi } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { useAuthStore } from '../../stores/auth-store';
import {
    setAccessToken,
    AUTH_UNAUTHORIZED_EVENT,
    type UnauthorizedEventDetail,
} from '../../lib/http/auth';
import { getUserProfileAPI } from '../../api/auth';
import { AppHttpError } from '../../lib/http/errors';
import { server } from '../msw/server';
import { http, HttpResponse } from 'msw';
import { API_URLS } from '../../api/urls';
import { validationError, unauthorizedError, serverError } from '../msw/utils';
import { AuthProvider } from '../../context/AuthContext';
import { useAuth } from '../../context/useAuth';
import { createTestQueryClient } from '../render-with-query';

describe('Error paths contract', () => {
    beforeEach(() => {
        useAuthStore.getState().resetAll();
    });

    it('422 from /users/me produces AppHttpError with code validation', async () => {
        setAccessToken('test-access-token');
        server.use(
            http.get(API_URLS.USER.ME, () => validationError('Invalid token format')),
        );

        try {
            await getUserProfileAPI();
            expect.unreachable('should have thrown');
        } catch (err) {
            expect(err).toBeInstanceOf(AppHttpError);
            expect((err as AppHttpError).code).toBe('validation');
            expect((err as AppHttpError).status).toBe(422);
        }
    });

    it('401 fires unauthorized event with request-time token detail', async () => {
        setAccessToken('test-access-token');
        expect(useAuthStore.getState().token).toBe('test-access-token');

        const eventSpy = vi.fn();
        window.addEventListener(AUTH_UNAUTHORIZED_EVENT, eventSpy);

        // Mirror AuthProvider: only clear when event identity matches current token.
        const cleanupListener = (event: Event) => {
            const detail = (event as CustomEvent<UnauthorizedEventDetail>).detail;
            const current = useAuthStore.getState().token;
            if (detail === undefined || detail.token === current) {
                useAuthStore.getState().clearAuth();
            }
        };
        window.addEventListener(AUTH_UNAUTHORIZED_EVENT, cleanupListener);

        server.use(
            http.get(API_URLS.USER.ME, () => unauthorizedError()),
        );

        try {
            await getUserProfileAPI();
        } catch {
            // expected
        }

        expect(eventSpy).toHaveBeenCalled();
        const detail = (eventSpy.mock.calls[0][0] as CustomEvent<UnauthorizedEventDetail>).detail;
        expect(detail).toEqual({ token: 'test-access-token' });
        expect(useAuthStore.getState().token).toBeNull();

        window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, eventSpy);
        window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, cleanupListener);
    });

    it('delayed A 401 does not log out already-logged-in B via real AuthProvider', async () => {
        const queryClient = createTestQueryClient();
        const wrapper = ({ children }: { children: ReactNode }) => (
            <QueryClientProvider client={queryClient}>
                <AuthProvider>{children}</AuthProvider>
            </QueryClientProvider>
        );

        // Bootstrap B first through AuthProvider.
        setAccessToken('tok-b');
        server.use(
            http.get(API_URLS.USER.ME, () =>
                HttpResponse.json({ id: 'b', username: 'bob' }),
            ),
        );

        const { result } = renderHook(() => useAuth(), { wrapper });
        await waitFor(() => {
            expect(result.current.isAuthenticated).toBe(true);
            expect(result.current.user).toEqual(
                expect.objectContaining({ id: 'b', username: 'bob' }),
            );
        });

        // Simulate a late 401 from an earlier A request (Axios stamped token A).
        await act(async () => {
            window.dispatchEvent(
                new CustomEvent(AUTH_UNAUTHORIZED_EVENT, {
                    detail: { token: 'tok-a' },
                }),
            );
            await Promise.resolve();
        });

        expect(useAuthStore.getState().token).toBe('tok-b');
        expect(result.current.isAuthenticated).toBe(true);
        expect(result.current.user).toEqual(
            expect.objectContaining({ id: 'b', username: 'bob' }),
        );
    });

    it('500 produces AppHttpError with code server', async () => {
        setAccessToken('test-access-token');
        server.use(
            http.get(API_URLS.USER.ME, () => serverError('Internal Server Error')),
        );

        try {
            await getUserProfileAPI();
            expect.unreachable('should have thrown');
        } catch (err) {
            expect(err).toBeInstanceOf(AppHttpError);
            expect((err as AppHttpError).code).toBe('server');
            expect((err as AppHttpError).status).toBe(500);
        }
    });

    it('network error produces AppHttpError with code network', async () => {
        setAccessToken('test-access-token');
        server.use(
            http.get(API_URLS.USER.ME, () => HttpResponse.error()),
        );

        try {
            await getUserProfileAPI();
            expect.unreachable('should have thrown');
        } catch (err) {
            expect(err).toBeInstanceOf(AppHttpError);
            expect((err as AppHttpError).code).toBe('network');
        }
    });
});
