import { describe, expect, it, beforeEach } from 'vitest';

import { useAuthStore } from '../../stores/auth-store';
import { setAccessToken } from '../../lib/http/auth';
import { AUTH_UNAUTHORIZED_EVENT } from '../../lib/http/auth';
import { getUserProfileAPI } from '../../api/auth';
import { AppHttpError } from '../../lib/http/errors';
import { server } from '../msw/server';
import { http, HttpResponse } from 'msw';
import { API_URLS } from '../../api/urls';
import { validationError, unauthorizedError, serverError } from '../msw/utils';

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

    it('401 fires unauthorized event (token cleared by AuthProvider listener)', async () => {
        setAccessToken('test-access-token');
        expect(useAuthStore.getState().token).toBe('test-access-token');

        const eventSpy = vi.fn();
        window.addEventListener(AUTH_UNAUTHORIZED_EVENT, eventSpy);

        // Simulate AuthProvider's event listener
        const cleanupListener = () => useAuthStore.getState().clearAuth();
        window.addEventListener(AUTH_UNAUTHORIZED_EVENT, cleanupListener);

        server.use(
            http.get(API_URLS.USER.ME, () => unauthorizedError()),
        );

        try {
            await getUserProfileAPI();
        } catch {
            // expected
        }

        expect(useAuthStore.getState().token).toBeNull();
        expect(eventSpy).toHaveBeenCalled();
        window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, eventSpy);
        window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, cleanupListener);
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
