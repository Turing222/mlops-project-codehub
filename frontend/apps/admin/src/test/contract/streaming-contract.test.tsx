import { describe, expect, it, beforeEach } from 'vitest';
import { waitFor } from '@testing-library/react';

import { useAuthStore } from '../../stores/auth-store';
import { setAccessToken, AUTH_UNAUTHORIZED_EVENT } from '../../lib/http/auth';
import { streamChatQuery } from '../../streams/chat-stream';
import { server } from '../msw/server';
import { http } from 'msw';
import { API_URLS } from '../../api/urls';
import { unauthorizedError } from '../msw/utils';

describe('Streaming contract', () => {
    beforeEach(() => {
        useAuthStore.getState().resetAll();
        setAccessToken('test-access-token');
    });

    it('stream returns meta, chunks, and [DONE] in correct format', async () => {
        const onMeta = vi.fn();
        const onChunk = vi.fn();
        const onDone = vi.fn();
        const onError = vi.fn();

        const controller = streamChatQuery(
            { query: 'Hello' },
            { onMeta, onChunk, onDone, onError },
        );

        await waitFor(() => {
            expect(onDone).toHaveBeenCalled();
        });
        controller.abort();

        expect(onMeta).toHaveBeenCalledWith(
            expect.objectContaining({
                type: 'meta',
                session_id: expect.any(String),
                session_title: expect.any(String),
            }),
        );

        expect(onChunk).toHaveBeenCalledWith(
            expect.objectContaining({
                type: 'chunk',
                content: expect.any(String),
            }),
        );

        expect(onError).not.toHaveBeenCalled();
    });

    it('stream 401 fires unauthorized event (token cleared by AuthProvider listener)', async () => {
        server.use(
            http.post(API_URLS.CHAT.QUERY_STREAM, () => unauthorizedError()),
        );

        const onMeta = vi.fn();
        const onChunk = vi.fn();
        const onDone = vi.fn();
        const onError = vi.fn();

        // Simulate AuthProvider's event listener
        const cleanupListener = () => useAuthStore.getState().clearAuth();
        window.addEventListener(AUTH_UNAUTHORIZED_EVENT, cleanupListener);

        streamChatQuery(
            { query: 'Hello' },
            { onMeta, onChunk, onDone, onError },
        );

        await waitFor(() => {
            expect(onError).toHaveBeenCalled();
        });

        expect(useAuthStore.getState().token).toBeNull();
        window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, cleanupListener);
    });

    it('stream request includes X-Idempotency-Key', async () => {
        const capturedHeaders: Record<string, string> = {};

        server.use(
            http.post(API_URLS.CHAT.QUERY_STREAM, async ({ request }) => {
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

        const onMeta = vi.fn();
        const onDone = vi.fn();
        const onError = vi.fn();

        const controller = streamChatQuery(
            { query: 'Hello' },
            { onMeta, onChunk: vi.fn(), onDone, onError },
        );

        await waitFor(() => {
            expect(capturedHeaders.idempotencyKey).toBeTruthy();
        });
        controller.abort();
    });
});
