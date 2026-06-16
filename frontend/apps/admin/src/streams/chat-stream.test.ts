import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { Mock } from 'vitest';
import { streamChatQuery, type StreamCallbacks } from './chat-stream';

vi.mock('../api/chat', () => ({
    sendQueryStreamAPI: vi.fn(),
}));

const { reportFrontendErrorEvent } = vi.hoisted(() => ({
    reportFrontendErrorEvent: vi.fn(),
}));
vi.mock('../lib/http/telemetry', () => ({
    reportFrontendErrorEvent,
    normalizeErrorMessage: (error: unknown) =>
        error instanceof Error ? error.message : String(error),
}));

import { sendQueryStreamAPI } from '../api/chat';

const mockSendQueryStreamAPI = vi.mocked(sendQueryStreamAPI);

function createFakeSSEResponse(chunks: string[]): Response {
    const encoder = new TextEncoder();
    let chunkIndex = 0;
    const stream = new ReadableStream({
        pull(controller) {
            if (chunkIndex < chunks.length) {
                controller.enqueue(encoder.encode(chunks[chunkIndex]));
                chunkIndex++;
            } else {
                controller.close();
            }
        },
    });
    return new Response(stream);
}

type MockCallbacks = StreamCallbacks & {
    onMeta: Mock<StreamCallbacks['onMeta']>;
    onStep: Mock<NonNullable<StreamCallbacks['onStep']>>;
    onChunk: Mock<StreamCallbacks['onChunk']>;
    onDone: Mock<StreamCallbacks['onDone']>;
    onError: Mock<StreamCallbacks['onError']>;
    onAbort: Mock<NonNullable<StreamCallbacks['onAbort']>>;
};

function createCallbacks(): MockCallbacks {
    return {
        onMeta: vi.fn(),
        onStep: vi.fn(),
        onChunk: vi.fn(),
        onDone: vi.fn(),
        onError: vi.fn(),
        onAbort: vi.fn(),
    };
}

beforeEach(() => {
    vi.restoreAllMocks();
    reportFrontendErrorEvent.mockClear();
});

describe('streamChatQuery', () => {
    it('invokes onMeta for meta event', async () => {
        const sseData = 'data: {"type":"meta","session_id":"s1","session_title":"Hello"}\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onMeta).toHaveBeenCalledOnce();
        });
        expect(callbacks.onMeta).toHaveBeenCalledWith(
            expect.objectContaining({ type: 'meta', session_id: 's1', session_title: 'Hello' }),
        );
    });

    it('invokes onChunk for chunk event', async () => {
        const sseData = 'data: {"type":"chunk","content":"hello"}\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onChunk).toHaveBeenCalledOnce();
        });
        expect(callbacks.onChunk).toHaveBeenCalledWith(
            expect.objectContaining({ type: 'chunk', content: 'hello' }),
        );
    });

    it('invokes onStep for step event', async () => {
        const sseData =
            'data: {"type":"step","step":"router-judge","status":"done","metrics":{"planner_ms":12}}\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onStep).toHaveBeenCalledOnce();
        });
        expect(callbacks.onStep).toHaveBeenCalledWith(
            expect.objectContaining({
                type: 'step',
                step: 'router-judge',
                status: 'done',
                metrics: { planner_ms: 12 },
            }),
        );
    });

    it('invokes onError and reports telemetry for an SSE error event', async () => {
        const sseData = 'data: {"type":"error","message":"LLM error"}\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onError).toHaveBeenCalledOnce();
        });
        expect(callbacks.onError.mock.calls[0][0].message).toBe('LLM error');
        expect(reportFrontendErrorEvent).toHaveBeenCalledWith(
            expect.objectContaining({
                eventType: 'stream_error',
                source: 'chat_stream',
                message: 'LLM error',
                metadata: expect.objectContaining({ phase: 'sse_error' }),
            }),
        );
    });

    it('invokes onDone when [DONE] received and reports nothing', async () => {
        const sseData = 'data: [DONE]\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onDone).toHaveBeenCalledOnce();
        });
        expect(reportFrontendErrorEvent).not.toHaveBeenCalled();
    });

    it('reports a truncated stream when it ends without [DONE]', async () => {
        const sseData = 'data: {"type":"chunk","content":"x"}\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onError).toHaveBeenCalledOnce();
        });
        expect(callbacks.onError.mock.calls[0][0].message).toBe('流式响应异常结束');
        expect(callbacks.onChunk).toHaveBeenCalledOnce();
        expect(reportFrontendErrorEvent).toHaveBeenCalledWith(
            expect.objectContaining({
                eventType: 'stream_error',
                message: '流式响应异常结束',
                metadata: expect.objectContaining({ phase: 'truncated' }),
            }),
        );
    });

    it('handles meta then chunk then [DONE] in order', async () => {
        const chunks = [
            'data: {"type":"meta","session_id":"s1","session_title":"T"}\n\n',
            'data: {"type":"chunk","content":"hi"}\n\n',
            'data: [DONE]\n\n',
        ];
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse(chunks));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onDone).toHaveBeenCalledOnce();
        });
        const callOrder = [
            callbacks.onMeta.mock.invocationCallOrder[0],
            callbacks.onChunk.mock.invocationCallOrder[0],
            callbacks.onDone.mock.invocationCallOrder[0],
        ];
        expect(callOrder).toEqual([...callOrder].sort((a, b) => a - b));
    });

    it('buffers partial SSE events across reads', async () => {
        const chunks = [
            'data: {"type":"me',
            'ta","session_id":"s1","session_title":"T"}\n\n',
            'data: [DONE]\n\n',
        ];
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse(chunks));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onMeta).toHaveBeenCalledOnce();
        });
        expect(callbacks.onMeta).toHaveBeenCalledWith(
            expect.objectContaining({ type: 'meta', session_id: 's1' }),
        );
    });

    it('warns on parse errors without reporting them, but reports the truncated stream', async () => {
        const sseData = 'data: {invalid json}\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(warnSpy).toHaveBeenCalled();
        });
        await vi.waitFor(() => {
            expect(callbacks.onError).toHaveBeenCalledOnce();
        });
        expect(callbacks.onError.mock.calls[0][0].message).toBe('流式响应异常结束');
        // Parse warnings stay as console.warn only; the single telemetry event is the truncation.
        expect(reportFrontendErrorEvent).toHaveBeenCalledTimes(1);
        expect(reportFrontendErrorEvent.mock.calls[0][0].metadata.phase).toBe('truncated');
    });

    it('reports a no-reader failure', async () => {
        mockSendQueryStreamAPI.mockResolvedValue(new Response(null, { status: 200 }));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onError).toHaveBeenCalledOnce();
        });
        expect(callbacks.onError.mock.calls[0][0].message).toBe('无法获取响应流');
        expect(reportFrontendErrorEvent).toHaveBeenCalledWith(
            expect.objectContaining({
                eventType: 'stream_error',
                message: '无法获取响应流',
                metadata: expect.objectContaining({ phase: 'no_reader' }),
            }),
        );
    });

    it('reports an unexpected exception', async () => {
        mockSendQueryStreamAPI.mockRejectedValue(new Error('network fail'));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onError).toHaveBeenCalledOnce();
        });
        expect(callbacks.onError.mock.calls[0][0].message).toBe('network fail');
        expect(reportFrontendErrorEvent).toHaveBeenCalledWith(
            expect.objectContaining({
                eventType: 'stream_error',
                message: 'network fail',
                metadata: expect.objectContaining({ phase: 'exception' }),
            }),
        );
    });

    it('includes client/session correlation in stream error metadata', async () => {
        mockSendQueryStreamAPI.mockResolvedValue(new Response(null, { status: 200 }));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test', clientRequestId: 'cr-1', sessionId: 's-9' }, callbacks);

        await vi.waitFor(() => {
            expect(reportFrontendErrorEvent).toHaveBeenCalledOnce();
        });
        expect(reportFrontendErrorEvent.mock.calls[0][0].metadata).toMatchObject({
            phase: 'no_reader',
            clientRequestId: 'cr-1',
            sessionId: 's-9',
        });
    });

    it('calls onAbort without reporting telemetry when the stream is aborted', async () => {
        const stream = new ReadableStream({
            pull() {
                // never resolves — stream stays open
            },
        });
        mockSendQueryStreamAPI.mockResolvedValue(new Response(stream));
        const callbacks = createCallbacks();

        const controller = streamChatQuery({ query: 'test' }, callbacks);
        controller.abort();

        await new Promise((r) => setTimeout(r, 50));
        expect(callbacks.onAbort).toHaveBeenCalledOnce();
        expect(callbacks.onDone).not.toHaveBeenCalled();
        expect(callbacks.onError).not.toHaveBeenCalled();
        expect(reportFrontendErrorEvent).not.toHaveBeenCalled();
    });
});
