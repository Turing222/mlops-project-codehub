import { sendQueryStreamAPI, sendRetryStreamAPI } from '../api/chat';
import { AppHttpError } from '../lib/http/errors';
import { normalizeErrorMessage, reportFrontendErrorEvent } from '../lib/http/telemetry';
import { chatStreamEventSchema } from '../schemas/chat';
import type { ChatStreamEvent } from '../schemas/chat';

type StartedEvent = Extract<ChatStreamEvent, { type: 'started' }>;
type MetaEvent = Extract<ChatStreamEvent, { type: 'meta' }>;
type ChunkEvent = Extract<ChatStreamEvent, { type: 'chunk' }>;
type StepEvent = Extract<ChatStreamEvent, { type: 'step' }>;
type ErrorEvent = Extract<ChatStreamEvent, { type: 'error' }>;

export class ChatStreamError extends Error {
    readonly errorCode?: string;
    readonly retryable: boolean;
    readonly generationRequestId?: string;
    readonly attempt?: number;

    constructor(event: ErrorEvent) {
        super(event.message || 'LLM 服务错误');
        this.name = 'ChatStreamError';
        this.errorCode = event.error_code;
        this.retryable = event.retryable === true;
        this.generationRequestId = event.generation_request_id;
        this.attempt = event.attempt;
    }
}

export type StreamCallbacks = {
    onStarted?: (event: StartedEvent) => void;
    onMeta: (event: MetaEvent) => void;
    onStep?: (event: StepEvent) => void;
    onChunk: (event: ChunkEvent) => void;
    onDone: () => void;
    onError: (error: Error) => void;
    onAbort?: () => void;
};

export type StreamOptions = {
    query: string;
    sessionId?: string;
    kbId?: string;
    clientRequestId?: string;
    enableExternalContext?: boolean;
    signal?: AbortSignal;
};

export type RetryStreamOptions = {
    generationRequestId: string;
    expectedAttempt: number;
    sessionId?: string;
    signal?: AbortSignal;
};

type StreamCorrelationOptions = {
    clientRequestId?: string;
    generationRequestId?: string;
    sessionId?: string;
    signal?: AbortSignal;
};

export function streamChatQuery(
    options: StreamOptions,
    callbacks: StreamCallbacks,
): AbortController {
    return startChatStream(
        {
            clientRequestId: options.clientRequestId,
            sessionId: options.sessionId,
            signal: options.signal,
        },
        (signal) => sendQueryStreamAPI({ ...options, signal }),
        callbacks,
    );
}

export function streamChatRetry(
    options: RetryStreamOptions,
    callbacks: StreamCallbacks,
): AbortController {
    return startChatStream(
        {
            generationRequestId: options.generationRequestId,
            sessionId: options.sessionId,
            signal: options.signal,
        },
        (signal) => sendRetryStreamAPI({
            generationRequestId: options.generationRequestId,
            expectedAttempt: options.expectedAttempt,
            signal,
        }),
        callbacks,
    );
}

function startChatStream(
    options: StreamCorrelationOptions,
    sendRequest: (signal: AbortSignal) => Promise<Response>,
    callbacks: StreamCallbacks,
): AbortController {
    const abortController = new AbortController();

    // 统一上报 chat stream 的 terminal failure；abort 不算错误，故在此处统一拦截。
    type StreamErrorPhase = 'no_reader' | 'sse_error' | 'truncated' | 'exception';
    const reportStreamError = (
        message: string,
        phase: StreamErrorPhase,
        correlation?: { requestId?: string; status?: number; errorCode?: string },
    ): void => {
        if (abortController.signal.aborted) {
            return;
        }
        const metadata: Record<string, string> = { phase };
        if (options.clientRequestId) {
            metadata.clientRequestId = options.clientRequestId;
        }
        if (options.sessionId) {
            metadata.sessionId = options.sessionId;
        }
        if (options.generationRequestId) {
            metadata.generationRequestId = options.generationRequestId;
        }
        reportFrontendErrorEvent({
            eventType: 'stream_error',
            source: 'chat_stream',
            message,
            requestId: correlation?.requestId,
            status: correlation?.status,
            errorCode: correlation?.errorCode,
            metadata,
        });
    };

    if (options.signal?.aborted) {
        abortController.abort();
        return abortController;
    }

    let parentAbortHandler: (() => void) | null = null;

    if (options.signal) {
        parentAbortHandler = () => abortController.abort();
        options.signal.addEventListener('abort', parentAbortHandler, { once: true });
    }

    (async () => {
        try {
            const response = await sendRequest(abortController.signal);

            const reader = response.body?.getReader();
            if (!reader) {
                reportStreamError('无法获取响应流', 'no_reader');
                callbacks.onError(new Error('无法获取响应流'));
                return;
            }

            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                if (abortController.signal.aborted) {
                    reader.cancel().catch(() => {});
                    callbacks.onAbort?.();
                    return;
                }
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                const events = buffer.split('\n\n');
                buffer = events.pop() || '';

                for (const event of events) {
                    const line = event.trim();
                    if (!line.startsWith('data: ')) continue;

                    const data = line.slice(6);

                    if (data === '[DONE]') {
                        callbacks.onDone();
                        return;
                    }

                    try {
                        const parsed = chatStreamEventSchema.parse(JSON.parse(data));

                        if (parsed.type === 'started') {
                            callbacks.onStarted?.(parsed);
                        } else if (parsed.type === 'meta') {
                            callbacks.onMeta(parsed);
                        } else if (parsed.type === 'step') {
                            callbacks.onStep?.(parsed);
                        } else if (parsed.type === 'chunk') {
                            callbacks.onChunk(parsed);
                        } else if (parsed.type === 'error') {
                            const streamError = new ChatStreamError(parsed);
                            reportStreamError(streamError.message, 'sse_error', {
                                errorCode: streamError.errorCode,
                            });
                            callbacks.onError(streamError);
                            return;
                        }
                    } catch (parseErr) {
                        console.warn('SSE 解析警告:', parseErr);
                    }
                }
            }

            // Stream ended without [DONE] — treat as error
            reportStreamError('流式响应异常结束', 'truncated');
            callbacks.onError(new Error('流式响应异常结束'));
        } catch (err: unknown) {
            if (abortController.signal.aborted) return;
            const correlation =
                err instanceof AppHttpError
                    ? { requestId: err.requestId, status: err.status, errorCode: err.code }
                    : undefined;
            reportStreamError(normalizeErrorMessage(err), 'exception', correlation);
            callbacks.onError(err instanceof Error ? err : new Error('请求处理失败，请稍后重试'));
        } finally {
            if (parentAbortHandler && options.signal) {
                options.signal.removeEventListener('abort', parentAbortHandler);
            }
        }
    })();

    return abortController;
}
