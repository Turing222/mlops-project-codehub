import { describe, expect, it, beforeEach } from 'vitest';

import { useAuthStore } from '../../stores/auth-store';
import { setAccessToken } from '../../lib/http/auth';
import { getUserProfileAPI } from '../../api/auth';
import { uploadUsersCSVAPI } from '../../api/users';
import { sendQueryStreamAPI } from '../../api/chat';
import { loginAPI } from '../../api/auth';
import { server } from '../msw/server';
import { buildUser } from '../msw/factories';
import { http, HttpResponse } from 'msw';
import { API_URLS } from '../../api/urls';

describe('Headers contract', () => {
    beforeEach(() => {
        useAuthStore.getState().resetAll();
    });

    it('axios requests include Authorization and X-Request-ID', async () => {
        setAccessToken('test-access-token');

        const capturedHeaders: Record<string, string> = {};

        server.use(
            http.get(API_URLS.USER.ME, ({ request }) => {
                capturedHeaders.authorization = request.headers.get('Authorization') ?? '';
                capturedHeaders.requestId = request.headers.get('X-Request-ID') ?? '';
                return HttpResponse.json(buildUser());
            }),
        );

        await getUserProfileAPI();

        expect(capturedHeaders.authorization).toBe('Bearer test-access-token');
        expect(capturedHeaders.requestId).toBeTruthy();
    });

    it('CSV upload includes X-Idempotency-Key', async () => {
        setAccessToken('test-access-token');

        const capturedHeaders: Record<string, string> = {};

        server.use(
            http.post(API_URLS.USER.CSV_UPLOAD, ({ request }) => {
                capturedHeaders.idempotencyKey = request.headers.get('X-Idempotency-Key') ?? '';
                capturedHeaders.contentType = request.headers.get('Content-Type') ?? '';
                return HttpResponse.json({
                    filename: 'test.csv',
                    total_rows: 1,
                    imported_rows: 1,
                    message: 'ok',
                });
            }),
        );

        const file = new File(['username,email\na,b@c.com'], 'test.csv', { type: 'text/csv' });
        await uploadUsersCSVAPI(file);

        expect(capturedHeaders.idempotencyKey).toBeTruthy();
        expect(capturedHeaders.contentType).toContain('multipart/form-data');
    });

    it('stream request includes Authorization, X-Request-ID, and X-Idempotency-Key', async () => {
        setAccessToken('test-access-token');

        const capturedHeaders: Record<string, string> = {};

        server.use(
            http.post(API_URLS.CHAT.QUERY_STREAM, async ({ request }) => {
                capturedHeaders.authorization = request.headers.get('Authorization') ?? '';
                capturedHeaders.requestId = request.headers.get('X-Request-ID') ?? '';
                capturedHeaders.idempotencyKey = request.headers.get('X-Idempotency-Key') ?? '';

                const encoder = new TextEncoder();
                const stream = new ReadableStream({
                    start(controller) {
                        controller.enqueue(encoder.encode(
                            `data: ${JSON.stringify({ type: 'meta', session_id: '1', session_title: 'Test' })}\n\n`,
                        ));
                        controller.enqueue(encoder.encode(
                            `data: ${JSON.stringify({ type: 'chunk', content: 'ok' })}\n\n`,
                        ));
                        controller.enqueue(encoder.encode('data: [DONE]\n\n'));
                        controller.close();
                    },
                });

                return new Response(stream, {
                    status: 200,
                    headers: { 'Content-Type': 'text/event-stream' },
                });
            }),
        );

        const res = await sendQueryStreamAPI({ query: 'hello' });
        expect(res.ok).toBe(true);

        expect(capturedHeaders.authorization).toBe('Bearer test-access-token');
        expect(capturedHeaders.requestId).toBeTruthy();
        expect(capturedHeaders.idempotencyKey).toBeTruthy();
    });

    it('login (public endpoint) does not include Authorization header', async () => {
        const capturedHeaders: Record<string, string> = {};

        server.use(
            http.post(API_URLS.AUTH.LOGIN, ({ request }) => {
                capturedHeaders.authorization = request.headers.get('Authorization') ?? 'NONE';
                return HttpResponse.json({
                    access_token: 'new-token',
                    token_type: 'bearer',
                });
            }),
        );

        await loginAPI({ username: 'admin', password: 'pass' });

        expect(capturedHeaders.authorization).toBe('NONE');
    });
});
