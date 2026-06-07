import { afterEach, describe, expect, it, vi } from 'vitest';

import { sendQueryStreamAPI } from './chat';
import { API_URLS, getApiBaseUrl, resolveApiUrl } from './urls';
import request, { createAuthorizedHeaders } from '../lib/http/client';
import { AUTH_UNAUTHORIZED_EVENT, notifyUnauthorized } from '../lib/http/auth';
import { normalizeHttpError } from '../lib/http/errors';
import { IDEMPOTENCY_KEY_HEADER, resolveIdempotencyKey } from '../lib/http/idempotency';
import { REQUEST_ID_HEADER } from '../lib/http/trace';
import { useAuthStore } from '../stores/auth-store';

describe('request configuration', () => {
    afterEach(() => {
        vi.unstubAllEnvs();
        vi.unstubAllGlobals();
    });

    it('uses explicit /api/v1 routes without duplicating the api prefix', () => {
        expect(request.getUri({ url: API_URLS.AUTH.LOGIN })).toBe('/api/v1/auth/login');
        expect(request.getUri({ url: API_URLS.USER.ME })).toBe('/api/v1/users/me');
    });

    it('resolves API URLs against VITE_API_BASE_URL when configured', () => {
        vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com/');

        expect(getApiBaseUrl()).toBe('https://api.example.com');
        expect(resolveApiUrl(API_URLS.AUTH.LOGIN)).toBe('https://api.example.com/api/v1/auth/login');
    });

    it('injects authorization and request id headers for outgoing requests', () => {
        useAuthStore.getState().setToken('test-token');

        const headers = createAuthorizedHeaders({ 'Content-Type': 'application/json' });

        expect(headers.Authorization).toBe('Bearer test-token');
        expect(headers[REQUEST_ID_HEADER]).toBeTruthy();
        expect(headers['Content-Type']).toBe('application/json');
    });

    it('reuses or generates idempotency keys through shared helpers', () => {
        const generatedKey = resolveIdempotencyKey();
        const explicitKey = resolveIdempotencyKey('cid-fixed');
        const headers = createAuthorizedHeaders(
            { 'Content-Type': 'application/json' },
            { idempotencyKey: explicitKey },
        );

        expect(generatedKey).toBeTruthy();
        expect(explicitKey).toBe('cid-fixed');
        expect(headers[IDEMPOTENCY_KEY_HEADER]).toBe('cid-fixed');
    });

    it('sends streaming chat requests to the same API namespace', async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response('', {
                status: 200,
                statusText: 'OK',
            }),
        );

        useAuthStore.getState().setToken('test-token');
        vi.stubGlobal('fetch', fetchMock);

        await sendQueryStreamAPI({ query: 'hello', sessionId: 'session-1', clientRequestId: 'cid-1' });

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(fetchMock).toHaveBeenCalledWith(
            API_URLS.CHAT.QUERY_STREAM,
            expect.objectContaining({
                method: 'POST',
                headers: expect.objectContaining({
                    'Content-Type': 'application/json',
                    Authorization: 'Bearer test-token',
                    [REQUEST_ID_HEADER]: expect.any(String),
                    [IDEMPOTENCY_KEY_HEADER]: 'cid-1',
                }),
            }),
        );

        const [, options] = fetchMock.mock.calls[0];

        expect(JSON.parse(String(options?.body))).toEqual({
            query: 'hello',
            session_id: 'session-1',
            kb_id: null,
            client_request_id: 'cid-1',
            enable_external_context: false,
        });
    });

    it('uses absolute stream URLs when VITE_API_BASE_URL is configured', async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response('', {
                status: 200,
                statusText: 'OK',
            }),
        );

        vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com');
        useAuthStore.getState().setToken('test-token');
        vi.stubGlobal('fetch', fetchMock);

        await sendQueryStreamAPI({ query: 'hello' });

        expect(fetchMock).toHaveBeenCalledWith(
            'https://api.example.com/api/v1/chat/query_stream',
            expect.objectContaining({
                method: 'POST',
            }),
        );
    });

    it('normalizes HTTP errors to a stable frontend shape', () => {
        const normalized = normalizeHttpError({
            isAxiosError: true,
            message: 'Request failed with status code 401',
            response: {
                status: 401,
                data: { detail: 'Token 无效或已过期' },
                headers: { 'x-request-id': 'req-123' },
            },
            config: {
                url: API_URLS.USER.ME,
                method: 'get',
            },
        });

        expect(normalized.code).toBe('unauthorized');
        expect(normalized.status).toBe(401);
        expect(normalized.requestId).toBe('req-123');
        expect(normalized.url).toBe(API_URLS.USER.ME);
        expect(normalized.method).toBe('GET');
        expect(normalized.message).toBe('Token 无效或已过期');
    });

    it('dispatches a shared unauthorized event for auth cleanup', () => {
        const listener = vi.fn();

        window.addEventListener(AUTH_UNAUTHORIZED_EVENT, listener);
        notifyUnauthorized();

        expect(listener).toHaveBeenCalledTimes(1);

        window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, listener);
    });
});
