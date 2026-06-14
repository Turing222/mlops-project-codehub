import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { useChatController } from './use-chat-controller';
import type { StreamCallbacks, StreamOptions } from '../../streams/chat-stream';
import type { SessionDetailResponse } from '../../types/chat';
import { TRACE_STEP_DEFS } from '../../types/agent-trace';

vi.mock('../../api/chat', () => ({
    sendQueryAPI: vi.fn(),
    sendQueryStreamAPI: vi.fn(),
    getSessionsAPI: vi.fn(),
    getSessionDetailAPI: vi.fn().mockResolvedValue({
        session: { id: 's1', title: 'Test', user_id: '1', created_at: '', updated_at: '', total_tokens: 0 },
        messages: [],
        total_messages: 0,
    }),
}));

vi.mock('../../streams/chat-stream', () => ({
    streamChatQuery: vi.fn(),
}));

vi.mock('../../context/useAuth', () => ({
    useAuth: () => ({
        user: { id: '1', is_superuser: false },
        refreshUser: vi.fn().mockResolvedValue(undefined),
    }),
}));

vi.mock('../../api/knowledge', () => ({
    getDefaultKBAPI: vi.fn().mockResolvedValue({ id: 'kb1', name: 'Default KB' }),
}));

vi.mock('../../query/keys/chat', () => ({
    chatKeys: {
        sessions: () => ['chat', 'sessions'],
        sessionDetail: (id: string) => ['chat', 'session', id],
    },
}));

// Factory lets individual tests control what useSessionDetailQuery returns.
let mockSessionDetailData: { data?: SessionDetailResponse; isLoading: boolean } = { data: undefined, isLoading: false };

vi.mock('../../query/hooks/chat', () => ({
    useSessionDetailQuery: () => mockSessionDetailData,
}));

import { streamChatQuery } from '../../streams/chat-stream';
import { getSessionDetailAPI } from '../../api/chat';
import { getDefaultKBAPI } from '../../api/knowledge';

const mockStreamChatQuery = vi.mocked(streamChatQuery);
const mockGetSessionDetailAPI = vi.mocked(getSessionDetailAPI);
const mockGetDefaultKBAPI = vi.mocked(getDefaultKBAPI);

function createWrapper() {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: { retry: false, gcTime: 0 },
            mutations: { retry: false },
        },
    });
    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    // Reset per-test session detail mock to "no data" default
    mockSessionDetailData = { data: undefined, isLoading: false };
    mockGetSessionDetailAPI.mockResolvedValue({
        session: { id: 's1', title: 'Test', user_id: '1', created_at: '', updated_at: '', total_tokens: 0 },
        messages: [],
        total_messages: 0,
    });
});

describe('useChatController', () => {
    it('aborts previous stream signal when sending a new query', async () => {
        let firstSignal: AbortSignal | undefined;

        mockStreamChatQuery.mockImplementation((options: StreamOptions) => {
            if (!firstSignal) {
                firstSignal = options.signal;
            }
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('first query');
        });

        expect(firstSignal).toBeDefined();
        expect(firstSignal!.aborted).toBe(false);

        await act(async () => {
            result.current.sendQuery('second query');
        });

        // The first signal should now be aborted
        expect(firstSignal!.aborted).toBe(true);
    });

    it('does not commit state in onDone if controller was aborted', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};
        let capturedSignal: AbortSignal | undefined;

        mockStreamChatQuery.mockImplementation((options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            capturedSignal = options.signal;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        // Abort the signal after sendQuery returns
        expect(capturedSignal).toBeDefined();
        // Manually abort to simulate the race condition
        // We need to abort the newController from the hook — but it's internal.
        // Instead, test by calling startNewChat which aborts it.
        act(() => {
            result.current.startNewChat();
        });

        // Now call onDone — the guard should prevent state commit
        const messageCountBefore = result.current.messages.length;
        act(() => {
            capturedCallbacks.onDone!();
        });

        // No new assistant message should be added
        expect(result.current.messages.length).toBe(messageCountBefore);
    });

    it('does not commit state in onError if controller was aborted', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        // Abort via startNewChat
        act(() => {
            result.current.startNewChat();
        });

        const messageCountBefore = result.current.messages.length;
        act(() => {
            capturedCallbacks.onError!(new Error('test error'));
        });

        // No error message should be appended
        expect(result.current.messages.length).toBe(messageCountBefore);
    });

    it('handles getSessionDetailAPI rejection without unhandled promise rejection', async () => {
        mockGetSessionDetailAPI.mockRejectedValue(new Error('network fail'));

        let capturedCallbacks: Partial<StreamCallbacks> = {};
        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        // Calling onDone should not throw unhandled rejection even if getSessionDetailAPI fails
        await act(async () => {
            capturedCallbacks.onDone!();
        });

        // .catch(() => {}) prevents unhandled rejection
        expect(true).toBe(true);
    });

    // --- Trace step tests ---

    it('initializes trace steps on sendQuery', async () => {
        mockStreamChatQuery.mockReturnValue(new AbortController());

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        expect(result.current.traceSteps).toHaveLength(0);

        await act(async () => {
            result.current.sendQuery('test');
        });

        expect(result.current.traceSteps).toHaveLength(TRACE_STEP_DEFS.length);
        expect(result.current.traceSteps[0].status).toBe('running');
        expect(result.current.traceSteps[0].id).toBe('receive-query');
        for (let i = 1; i < result.current.traceSteps.length; i++) {
            expect(result.current.traceSteps[i].status).toBe('idle');
        }
    });

    it('advances trace steps on onMeta', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        act(() => {
            result.current.setChatMode('rag');
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
        });

        // Steps 0-1 should be done, step 2 (kb-search) running, others skipped
        expect(result.current.traceSteps[0].status).toBe('done');
        expect(result.current.traceSteps[1].status).toBe('done');
        expect(result.current.traceSteps[2].status).toBe('running');
        expect(result.current.traceSteps[2].id).toBe('kb-search');
        expect(result.current.traceSteps[3].status).toBe('skipped');
        expect(result.current.traceSteps[4].status).toBe('skipped');
    });

    it('advances trace steps on first onChunk', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        act(() => {
            result.current.setChatMode('rag');
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
        });

        act(() => {
            capturedCallbacks.onChunk!({ type: 'chunk', content: 'Hello' });
        });

        expect(result.current.traceSteps[6].status).toBe('running');
        expect(result.current.traceSteps[6].id).toBe('generate-answer');
    });

    it('marks all remaining steps done on onDone', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        act(() => {
            result.current.setChatMode('rag');
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
            capturedCallbacks.onChunk!({ type: 'chunk', content: 'Hello' });
        });

        await act(async () => {
            capturedCallbacks.onDone!();
        });

        for (const step of result.current.traceSteps) {
            if (step.id === 'local-search' || step.id === 'web-search') {
                expect(step.status).toBe('skipped');
            } else {
                expect(step.status).toBe('done');
            }
        }
    });

    it('marks running step as error and later steps as skipped on onError', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        act(() => {
            result.current.setChatMode('rag');
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
        });

        // Step 2 (kb-search) is running at this point
        act(() => {
            capturedCallbacks.onError!(new Error('fail'));
        });

        const runningIdx = result.current.traceSteps.findIndex((s) => s.status === 'error');
        expect(runningIdx).toBe(2);

        for (let i = runningIdx + 1; i < result.current.traceSteps.length; i++) {
            expect(result.current.traceSteps[i].status).toBe('skipped');
        }
    });

    it('clears trace on startNewChat', async () => {
        mockStreamChatQuery.mockReturnValue(new AbortController());

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        expect(result.current.traceSteps.length).toBeGreaterThan(0);

        act(() => {
            result.current.startNewChat();
        });

        expect(result.current.traceSteps).toHaveLength(0);
        expect(result.current.citations).toHaveLength(0);
    });

    it('parses citations from search_context after onDone', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        mockGetSessionDetailAPI.mockResolvedValue({
            session: { id: 's1', title: 'Test', user_id: '1', created_at: '', updated_at: '', total_tokens: 0 },
            messages: [{
                id: 'm1',
                session_id: 's1',
                role: 'assistant',
                content: 'answer',
                status: 'success',
                search_context: {
                    metrics: {
                        retrieve_ms: 42,
                        candidate_count: 20,
                        hit_count: 4,
                        retrieval_mode: 'hybrid',
                        rerank_used: true,
                    },
                    citations: [
                        { document_name: 'doc1.pdf', chunk_id: 'c1', score: 0.92, summary: 'Passage one.' },
                        { document_name: 'report.docx', chunk_id: 'c2', score: 0.78, summary: 'Passage two.' },
                    ],
                },
                message_metadata: {
                    metrics: {
                        e2e_first_token_ms: 320,
                        worker_total_latency_ms: 1200,
                        llm_generate_ms: 900,
                        tokens_per_second: 11.5,
                    },
                },
                created_at: '',
                updated_at: '',
            }],
            total_messages: 1,
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
            capturedCallbacks.onChunk!({ type: 'chunk', content: 'answer' });
        });

        await act(async () => {
            capturedCallbacks.onDone!();
        });

        expect(result.current.citations).toHaveLength(2);
        expect(result.current.citations[0].documentName).toBe('doc1.pdf');
        expect(result.current.citations[1].documentName).toBe('report.docx');
        expect(result.current.traceSteps.find((step) => step.id === 'kb-search')?.durationMs).toBe(42);
        expect(result.current.traceSteps.find((step) => step.id === 'generate-answer')?.metricDetails?.first_token_latency_ms).toBe(320);
        expect(result.current.traceSteps.find((step) => step.id === 'complete')?.durationMs).toBe(1200);
    });

    it('handles empty or malformed search_context gracefully', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        mockGetSessionDetailAPI.mockResolvedValue({
            session: { id: 's1', title: 'Test', user_id: '1', created_at: '', updated_at: '', total_tokens: 0 },
            messages: [{
                id: 'm1',
                session_id: 's1',
                role: 'assistant',
                content: 'answer',
                status: 'success',
                created_at: '',
                updated_at: '',
            }],
            total_messages: 1,
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
            capturedCallbacks.onChunk!({ type: 'chunk', content: 'answer' });
        });

        await act(async () => {
            capturedCallbacks.onDone!();
        });

        expect(result.current.citations).toHaveLength(0);
    });

    // P2-9 — historical session: citations derived from useEffect watching sessionDetailData
    it('derives citations from historical session via useSessionDetailQuery', async () => {
        // Simulate useSessionDetailQuery returning a session with search_context
        const historicalDetail = {
            session: { id: 'hist-1', title: 'History', user_id: '1', created_at: '', updated_at: '', total_tokens: 50 },
            messages: [
                {
                    id: 'h-m1',
                    session_id: 'hist-1',
                    role: 'user' as const,
                    content: 'question',
                    status: 'success' as const,
                    created_at: '',
                    updated_at: '',
                },
                {
                    id: 'h-m2',
                    session_id: 'hist-1',
                    role: 'assistant' as const,
                    content: 'historical answer',
                    status: 'success' as const,
                    search_context: {
                        citations: [
                            { document_name: 'hist-doc.pdf', chunk_id: 'hc1', score: 0.85, summary: 'Historical passage.' },
                        ],
                    },
                    created_at: '',
                    updated_at: '',
                },
            ],
            total_messages: 2,
        };

        const { result, rerender } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        // Citations should be empty before any session is selected
        expect(result.current.citations).toHaveLength(0);

        // Step 1: selectSession switches to history mode
        act(() => {
            result.current.selectSession({
                id: 'hist-1',
                title: 'History',
                user_id: '1',
                created_at: '',
                updated_at: '',
                total_tokens: 50,
            });
        });

        // Step 2: simulate useSessionDetailQuery resolving with data.
        // Wrapped in act() so React flushes the useEffect before assertions run.
        act(() => {
            mockSessionDetailData = { data: historicalDetail, isLoading: false };
            rerender();
        });

        // useEffect should have fired and populated citations from the last assistant message
        expect(result.current.citations).toHaveLength(1);
        expect(result.current.citations[0].documentName).toBe('hist-doc.pdf');
        expect(result.current.citations[0].relevanceScore).toBe(0.85);
    });

    it('retryFailedMessage deletes the error message and retries with the original clientRequestId', async () => {
        const capturedOptions: StreamOptions[] = [];
        mockStreamChatQuery.mockImplementation((options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedOptions.push(options);
            callbacks.onError!(new Error('Immediate fail'));
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('query one');
        });

        expect(result.current.messages).toHaveLength(2);
        const errorMessage = result.current.messages[1];
        expect(errorMessage.status).toBe('failed');
        expect(capturedOptions).toHaveLength(1);
        const firstClientId = capturedOptions[0].clientRequestId;
        expect(firstClientId).toBeDefined();

        await act(async () => {
            result.current.retryFailedMessage(errorMessage.id);
        });

        expect(result.current.messages).toHaveLength(2);
        expect(capturedOptions).toHaveLength(2);
        
        const secondClientId = capturedOptions[1].clientRequestId;
        expect(secondClientId).toBeDefined();
        expect(secondClientId).toBe(firstClientId);
    });

    it('preserves historical messages when sending a new query in an active historical session', async () => {
        const historicalDetail = {
            session: { id: 'hist-1', title: 'History', user_id: '1', created_at: '', updated_at: '', total_tokens: 50 },
            messages: [
                {
                    id: 'h-m1',
                    session_id: 'hist-1',
                    role: 'user' as const,
                    content: 'old question',
                    status: 'success' as const,
                    created_at: '',
                    updated_at: '',
                },
                {
                    id: 'h-m2',
                    session_id: 'hist-1',
                    role: 'assistant' as const,
                    content: 'old answer',
                    status: 'success' as const,
                    created_at: '',
                    updated_at: '',
                },
            ],
            total_messages: 2,
        };

        mockStreamChatQuery.mockReturnValue(new AbortController());

        const { result, rerender } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        act(() => {
            result.current.selectSession({
                id: 'hist-1',
                title: 'History',
                user_id: '1',
                created_at: '',
                updated_at: '',
                total_tokens: 50,
            });
        });

        act(() => {
            mockSessionDetailData = { data: historicalDetail, isLoading: false };
            rerender();
        });

        expect(result.current.messages).toHaveLength(2);
        expect(result.current.messages[0].content).toBe('old question');

        await act(async () => {
            result.current.sendQuery('new question');
        });

        expect(result.current.messages).toHaveLength(3);
        expect(result.current.messages[0].content).toBe('old question');
        expect(result.current.messages[1].content).toBe('old answer');
        expect(result.current.messages[2].content).toBe('new question');
    });

    describe('chatMode and RAG/Normal dialogue options', () => {
        it('should default chatMode to normal', () => {
            const { result } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });
            expect(result.current.chatMode).toBe('normal');
        });

        it('should update chatMode when setChatMode is called', () => {
            const { result } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });
            act(() => {
                result.current.setChatMode('rag');
            });
            expect(result.current.chatMode).toBe('rag');
        });

        it('should reset chatMode to normal when startNewChat is called', () => {
            const { result } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });
            act(() => {
                result.current.setChatMode('rag');
            });
            expect(result.current.chatMode).toBe('rag');

            act(() => {
                result.current.startNewChat();
            });
            expect(result.current.chatMode).toBe('normal');
        });

        it('should sync chatMode when selectSession is called', () => {
            const { result } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            act(() => {
                result.current.selectSession({
                    id: 's-rag',
                    title: 'RAG session',
                    user_id: '1',
                    kb_id: 'kb-active',
                    created_at: '',
                    updated_at: '',
                });
            });
            expect(result.current.chatMode).toBe('rag');

            act(() => {
                result.current.selectSession({
                    id: 's-normal',
                    title: 'Normal session',
                    user_id: '1',
                    kb_id: null,
                    created_at: '',
                    updated_at: '',
                });
            });
            expect(result.current.chatMode).toBe('normal');
        });

        it('should fetch default knowledge base ID and pass it during RAG chat initiation', async () => {
            mockGetDefaultKBAPI.mockResolvedValue({ id: 'resolved-kb-id', name: 'My KB' });
            mockStreamChatQuery.mockReturnValue(new AbortController());

            const { result } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            act(() => {
                result.current.setChatMode('rag');
            });

            await act(async () => {
                await result.current.sendQuery('hello RAG');
            });

            expect(mockGetDefaultKBAPI).toHaveBeenCalledTimes(1);
            expect(mockStreamChatQuery).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: 'hello RAG',
                    kbId: 'resolved-kb-id',
                }),
                expect.any(Object),
            );
        });

        it('should not pass kbId during normal chat initiation', async () => {
            mockStreamChatQuery.mockReturnValue(new AbortController());

            const { result } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            await act(async () => {
                await result.current.sendQuery('hello normal');
            });

            expect(mockGetDefaultKBAPI).not.toHaveBeenCalled();
            expect(mockStreamChatQuery).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: 'hello normal',
                    kbId: undefined,
                }),
                expect.any(Object),
            );
        });

        it('should enable external context during enhanced RAG chat initiation', async () => {
            mockGetDefaultKBAPI.mockResolvedValue({ id: 'resolved-kb-id', name: 'My KB' });
            mockStreamChatQuery.mockReturnValue(new AbortController());

            const { result } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            act(() => {
                result.current.setChatMode('web_rag');
            });

            await act(async () => {
                await result.current.sendQuery('latest public info');
            });

            expect(mockStreamChatQuery).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: 'latest public info',
                    enableExternalContext: true,
                }),
                expect.any(Object),
            );
        });
    });
});
