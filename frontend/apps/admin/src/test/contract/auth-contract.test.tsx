import { describe, expect, it, beforeEach } from 'vitest';

import { loginAPI } from '../../api/auth';
import { getUserProfileAPI } from '../../api/auth';
import { useAuthStore } from '../../stores/auth-store';
import { AppHttpError } from '../../lib/http/errors';
import { server } from '../msw/server';
import { unauthorizedError, validationError } from '../msw/utils';
import { http } from 'msw';
import { API_URLS } from '../../api/urls';

describe('Auth contract', () => {
    beforeEach(() => {
        useAuthStore.getState().resetAll();
    });

    it('login success stores token and fetches /users/me', async () => {
        await loginAPI({ username: 'admin', password: 'password123' });

        expect(useAuthStore.getState().token).toBeNull();

        const authRes = await loginAPI({ username: 'admin', password: 'password123' });
        expect(authRes.access_token).toBe('test-access-token');

        useAuthStore.getState().setToken(authRes.access_token);

        const profile = await getUserProfileAPI();
        expect(profile.username).toBe('admin');
        expect(profile.is_superuser).toBe(true);
    });

    it('401 on login does not set token', async () => {
        server.use(
            http.post(API_URLS.AUTH.LOGIN, () => unauthorizedError('Incorrect username or password')),
        );

        try {
            await loginAPI({ username: 'bad-user', password: 'wrong-pass' });
            expect.unreachable('should have thrown');
        } catch (err) {
            expect(err).toBeInstanceOf(AppHttpError);
            expect((err as AppHttpError).code).toBe('unauthorized');
        }

        expect(useAuthStore.getState().token).toBeNull();
    });

    it('422 on login produces validation error code', async () => {
        server.use(
            http.post(API_URLS.AUTH.LOGIN, () => validationError('Field required')),
        );

        try {
            await loginAPI({ username: 'admin', password: 'password123' });
            expect.unreachable('should have thrown');
        } catch (err) {
            expect(err).toBeInstanceOf(AppHttpError);
            expect((err as AppHttpError).code).toBe('validation');
            expect((err as AppHttpError).status).toBe(422);
        }
    });
});
