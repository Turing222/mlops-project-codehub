import { describe, expect, it, beforeEach } from 'vitest';

import { useAuthStore } from '../../stores/auth-store';
import { setAccessToken } from '../../lib/http/auth';
import { queryUserAPI } from '../../api/users';
import { AppHttpError } from '../../lib/http/errors';
import { server } from '../msw/server';
import { validationError } from '../msw/utils';
import { http } from 'msw';
import { API_URLS } from '../../api/urls';

describe('Admin users contract', () => {
    beforeEach(() => {
        useAuthStore.getState().resetAll();
        setAccessToken('test-access-token');
    });

    it('search by username returns user from API', async () => {
        const user = await queryUserAPI({ username: 'admin' });
        expect(user.username).toBe('admin');
    });

    it('backend 422 response produces AppHttpError with code validation', async () => {
        server.use(
            http.get(API_URLS.USER.QUERY, () => validationError('Invalid query')),
        );
        try {
            await queryUserAPI({ username: 'admin' });
            expect.unreachable('should have thrown');
        } catch (err) {
            expect(err).toBeInstanceOf(AppHttpError);
            expect((err as AppHttpError).code).toBe('validation');
        }
    });
});
