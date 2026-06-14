import { http } from 'msw';

import { API_URLS } from '../../../api/urls';
import { buildSessionListResponse, buildSessionDetailResponse } from '../factories';
import { requireAuth, validationError } from '../utils';

export const chatHandlers = [
    http.get(API_URLS.CHAT.SESSIONS, ({ request }) => {
        const auth = requireAuth(request);
        if (!auth.authorized) return auth.response;

        const url = new URL(request.url);
        const skip = Number(url.searchParams.get('skip') ?? 0);
        const limit = Number(url.searchParams.get('limit') ?? 50);

        return Response.json(buildSessionListResponse({ skip, limit }));
    }),

    http.get(API_URLS.CHAT.SESSION_DETAIL(':id'), ({ request, params }) => {
        const auth = requireAuth(request);
        if (!auth.authorized) return auth.response;

        return Response.json(buildSessionDetailResponse(params.id as string));
    }),

    http.post(API_URLS.CHAT.QUERY_STREAM, async ({ request }) => {
        const auth = requireAuth(request);
        if (!auth.authorized) return auth.response;

        const idempotencyKey = request.headers.get('X-Idempotency-Key');
        if (!idempotencyKey) {
            return validationError('X-Idempotency-Key required');
        }

        const body = await request.json() as { query?: string };
        const sessionId = 'stream-session-1';
        const sessionTitle = body?.query?.slice(0, 20) ?? 'New Session';

        const encoder = new TextEncoder();
        const stream = new ReadableStream({
            start(controller) {
                controller.enqueue(encoder.encode(
                    `data: ${JSON.stringify({ type: 'meta', session_id: sessionId, session_title: sessionTitle, message_id: 'msg-1' })}\n\n`,
                ));
                controller.enqueue(encoder.encode(
                    `data: ${JSON.stringify({ type: 'chunk', content: 'Hello ' })}\n\n`,
                ));
                controller.enqueue(encoder.encode(
                    `data: ${JSON.stringify({ type: 'chunk', content: 'world' })}\n\n`,
                ));
                controller.enqueue(encoder.encode('data: [DONE]\n\n'));
                controller.close();
            },
        });

        return new Response(stream, {
            status: 200,
            headers: {
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache',
            },
        });
    }),
];
