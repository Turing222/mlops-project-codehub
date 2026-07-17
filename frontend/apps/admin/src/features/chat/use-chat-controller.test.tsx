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
    getGenerationRequestAPI: vi.fn().mockRejectedValue(new Error('not found')),
    resolveGenerationRequestAPI: vi.fn().mockRejectedValue(new Error('not found')),
}));

vi.mock('../../streams/chat-stream', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../../streams/chat-stream')>()),
    streamChatQuery: vi.fn(),
    streamChatRetry: vi.fn(),
}));

const mockAuthState = vi.hoisted(() => ({
    user: { id: '1', is_superuser: false } as { id: string; is_superuser: boolean } | null,
}));

vi.mock('../../context/useAuth', () => ({
    useAuth: () => ({
        get user() {
            return mockAuthState.user;
        },
        refreshUser: vi.fn().mockResolvedValue(undefined),
    }),
}));

vi.mock('../../api/knowledge', () => ({
    uploadKBFileAPI: vi.fn(),
    getKBTaskStatusAPI: vi.fn(),
}));

vi.mock('../../api/repo-analysis', () => ({
    submitRepoReadmeCheckAPI: vi.fn(),
    getRepoAnalysisRunAPI: vi.fn(),
}));

const mockDefaultKbState = vi.hoisted(() => ({
    data: undefined as { id: string; name: string } | undefined,
    fetchCount: 0,
}));

vi.mock('../../query/hooks/knowledge', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../query/hooks/knowledge')>();
    return {
        ...actual,
        useDefaultKBQuery: () => ({
            get data() {
                return mockDefaultKbState.data;
            },
        }),
        defaultKBQueryOptions: () => ({
            queryKey: ['knowledge', 'default'],
            queryFn: async () => {
                mockDefaultKbState.fetchCount += 1;
                mockDefaultKbState.data = mockDefaultKbState.data ?? {
                    id: 'kb1',
                    name: 'Default KB',
                };
                return mockDefaultKbState.data;
            },
            staleTime: Infinity,
        }),
    };
});

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
import { uploadKBFileAPI } from '../../api/knowledge';
import { submitRepoReadmeCheckAPI } from '../../api/repo-analysis';

const mockStreamChatQuery = vi.mocked(streamChatQuery);
const mockGetSessionDetailAPI = vi.mocked(getSessionDetailAPI);
const mockUploadKBFileAPI = vi.mocked(uploadKBFileAPI);
const mockSubmitRepoReadmeCheckAPI = vi.mocked(submitRepoReadmeCheckAPI);

function createWrapper(queryClient?: QueryClient) {
    const client = queryClient ?? new QueryClient({
        defaultOptions: {
            queries: { retry: false, gcTime: 0 },
            mutations: { retry: false },
        },
    });
    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
}

function createTestClient() {
    return new QueryClient({
        defaultOptions: {
            queries: { retry: false, gcTime: 0 },
            mutations: { retry: false },
        },
    });
}

beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState.user = { id: '1', is_superuser: false };
    mockDefaultKbState.data = undefined;
    mockDefaultKbState.fetchCount = 0;
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

    it('advances trace steps from worker step events', async () => {
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
            capturedCallbacks.onStarted?.({ type: 'started' });
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
            capturedCallbacks.onStep?.({
                type: 'step',
                step: 'router-judge',
                status: 'running',
            });
            capturedCallbacks.onStep?.({
                type: 'step',
                step: 'router-judge',
                status: 'done',
                metrics: { planner_ms: 5 },
            });
            capturedCallbacks.onStep?.({
                type: 'step',
                step: 'kb-search',
                status: 'running',
            });
        });

        expect(result.current.traceSteps[0].status).toBe('done');
        expect(result.current.traceSteps[1].status).toBe('done');
        expect(result.current.traceSteps[2].status).toBe('running');
        expect(result.current.traceSteps[2].id).toBe('kb-search');
        expect(result.current.traceSteps[3].status).toBe('skipped');
        expect(result.current.traceSteps[4].status).toBe('skipped');
    });

    it('advances trace steps on generate-answer step event', async () => {
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
            capturedCallbacks.onStep?.({
                type: 'step',
                step: 'generate-answer',
                status: 'running',
            });
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
            capturedCallbacks.onStep?.({
                type: 'step',
                step: 'kb-search',
                status: 'running',
            });
        });

        // Step 2 (kb-search) is running at this point
        await act(async () => {
            capturedCallbacks.onError!(new Error('fail'));
            await Promise.resolve();
            await Promise.resolve();
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

    it('re-selecting the same historical session is a no-op and preserves hydration for live mode', async () => {
        const historicalDetail = {
            session: {
                id: 'hist-1',
                title: 'History',
                user_id: '1',
                kb_id: 'kb-1',
                created_at: '',
                updated_at: '',
                total_tokens: 50,
            },
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
                    search_context: {
                        citations: [
                            {
                                document_name: 'hist-doc.pdf',
                                chunk_id: 'hc1',
                                score: 0.85,
                                summary: 'Historical passage.',
                            },
                        ],
                        metrics: {
                            external_context_used: true,
                        },
                    },
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

        const histSession = {
            id: 'hist-1',
            title: 'History',
            user_id: '1',
            kb_id: 'kb-1',
            created_at: '',
            updated_at: '',
            total_tokens: 50,
        };

        act(() => {
            result.current.selectSession(histSession);
        });
        act(() => {
            mockSessionDetailData = { data: historicalDetail, isLoading: false };
            rerender();
        });

        expect(result.current.chatMode).toBe('web_rag');
        expect(result.current.citations).toHaveLength(1);
        expect(result.current.messages).toHaveLength(2);

        // Sidebar re-clicks the same session — must not clear hydration.
        act(() => {
            result.current.selectSession(histSession);
        });

        expect(result.current.chatMode).toBe('web_rag');
        expect(result.current.citations).toHaveLength(1);
        expect(result.current.citations[0].documentName).toBe('hist-doc.pdf');
        expect(result.current.messages).toHaveLength(2);

        // Enter live mode via a new send; historical messages must still be present.
        await act(async () => {
            result.current.sendQuery('follow up');
        });

        expect(result.current.messages).toHaveLength(3);
        expect(result.current.messages[0].content).toBe('old question');
        expect(result.current.messages[1].content).toBe('old answer');
        expect(result.current.messages[2].content).toBe('follow up');
    });

    it('selectSession during streaming aborts the stream and ignores late callbacks', async () => {
        let streamSignal: AbortSignal | undefined;
        let callbacks: Partial<StreamCallbacks> = {};
        mockStreamChatQuery.mockImplementation((options: StreamOptions, cb: StreamCallbacks) => {
            streamSignal = options.signal;
            callbacks = cb;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('in flight');
        });
        expect(result.current.isStreaming).toBe(true);
        expect(streamSignal?.aborted).toBe(false);

        act(() => {
            result.current.selectSession({
                id: 'hist-other',
                title: 'Other',
                user_id: '1',
                created_at: '',
                updated_at: '',
                total_tokens: 0,
            });
        });

        expect(streamSignal?.aborted).toBe(true);
        expect(result.current.isStreaming).toBe(false);
        expect(result.current.activeSessionId).toBe('hist-other');
        // selectSession clears live messages while waiting for detail.
        expect(result.current.messages).toEqual([]);

        const messageCount = result.current.messages.length;
        act(() => {
            callbacks.onChunk!({ type: 'chunk', content: 'should not land' });
            callbacks.onDone!();
            callbacks.onError!(new Error('late'));
        });
        expect(result.current.messages.length).toBe(messageCount);
        expect(result.current.activeSessionId).toBe('hist-other');
    });

    it('selectSession while post-done detail is pending ignores late detail write', async () => {
        let streamSignal: AbortSignal | undefined;
        let callbacks: Partial<StreamCallbacks> = {};
        let resolveDetail: ((value: SessionDetailResponse) => void) | undefined;

        mockStreamChatQuery.mockImplementation((options: StreamOptions, cb: StreamCallbacks) => {
            streamSignal = options.signal;
            callbacks = cb;
            return new AbortController();
        });
        mockGetSessionDetailAPI.mockImplementation(
            () =>
                new Promise<SessionDetailResponse>((resolve) => {
                    resolveDetail = resolve;
                }),
        );

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('hello');
        });

        await act(async () => {
            callbacks.onMeta!({
                type: 'meta',
                session_id: 'stream-s1',
                session_title: 'Streamed',
                message_id: 'm1',
            });
            callbacks.onChunk!({ type: 'chunk', content: 'partial' });
            callbacks.onDone!();
        });

        expect(result.current.isStreaming).toBe(false);
        expect(result.current.activeSessionId).toBe('stream-s1');
        expect(mockGetSessionDetailAPI).toHaveBeenCalled();
        expect(resolveDetail).toBeDefined();

        act(() => {
            result.current.selectSession({
                id: 'hist-2',
                title: 'History 2',
                user_id: '1',
                created_at: '',
                updated_at: '',
                total_tokens: 10,
            });
        });

        expect(streamSignal?.aborted).toBe(true);
        expect(result.current.activeSessionId).toBe('hist-2');

        await act(async () => {
            resolveDetail!({
                session: {
                    id: 'stream-s1',
                    title: 'Should not win',
                    user_id: '1',
                    created_at: '',
                    updated_at: '',
                    total_tokens: 99,
                },
                messages: [
                    {
                        id: 'old-1',
                        session_id: 'stream-s1',
                        role: 'user',
                        content: 'stale from detail',
                        status: 'success',
                        created_at: '',
                        updated_at: '',
                    },
                ],
                total_messages: 1,
            });
        });

        // Late detail must not overwrite the newly selected session.
        expect(result.current.activeSessionId).toBe('hist-2');
        expect(result.current.messages.some((m) => m.content === 'stale from detail')).toBe(false);
    });

    it('does not expose explicit retry when the backend flag is missing', () => {
        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        expect(result.current.retryFailedMessage).toBeUndefined();
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
            mockDefaultKbState.data = undefined;
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

            expect(mockDefaultKbState.fetchCount).toBe(1);
            expect(mockStreamChatQuery).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: 'hello RAG',
                    kbId: 'kb1',
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

            expect(mockDefaultKbState.fetchCount).toBe(0);
            expect(mockStreamChatQuery).toHaveBeenCalledWith(
                expect.objectContaining({
                    query: 'hello normal',
                    kbId: undefined,
                }),
                expect.any(Object),
            );
        });

        it('should enable external context during enhanced RAG chat initiation', async () => {
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

        it('resolves default KB once then reuses query data on subsequent RAG sends', async () => {
            mockStreamChatQuery.mockReturnValue(new AbortController());

            const { result, rerender } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            act(() => {
                result.current.setChatMode('rag');
            });

            await act(async () => {
                await result.current.sendQuery('first RAG');
            });
            // After fetchQuery, observer re-reads cached defaultKb on next render.
            rerender();

            await act(async () => {
                await result.current.sendQuery('second RAG');
            });

            expect(mockDefaultKbState.fetchCount).toBe(1);
            expect(mockStreamChatQuery).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    query: 'second RAG',
                    kbId: 'kb1',
                }),
                expect.any(Object),
            );
        });

        it('re-resolves default KB after identity teardown clears query cache', async () => {
            mockStreamChatQuery.mockReturnValue(new AbortController());
            const queryClient = createTestClient();

            const { result, rerender } = renderHook(() => useChatController(), {
                wrapper: createWrapper(queryClient),
            });

            act(() => {
                result.current.setChatMode('rag');
            });

            await act(async () => {
                await result.current.sendQuery('owned by A');
            });
            expect(mockDefaultKbState.fetchCount).toBe(1);

            // Simulate AuthProvider terminateIdentitySession: clear cache + switch user.
            await act(async () => {
                queryClient.clear();
            });
            mockDefaultKbState.data = undefined;
            mockAuthState.user = { id: '2', is_superuser: false };
            rerender();

            act(() => {
                result.current.setChatMode('rag');
            });
            await act(async () => {
                await result.current.sendQuery('owned by B');
            });

            expect(mockDefaultKbState.fetchCount).toBe(2);
        });
    });

    describe('identity lifecycle reset', () => {
        it('clears local chat runtime when confirmed user becomes anonymous', async () => {
            let capturedSignal: AbortSignal | undefined;
            mockStreamChatQuery.mockImplementation((options: StreamOptions) => {
                capturedSignal = options.signal;
                return new AbortController();
            });

            const { result, rerender } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            await act(async () => {
                await result.current.sendQuery('hello from A');
            });
            act(() => {
                result.current.setChatMode('rag');
                result.current.setIsIngestionSidebarOpen(true);
            });

            expect(result.current.messages.length).toBeGreaterThan(0);
            expect(capturedSignal?.aborted).toBe(false);

            mockAuthState.user = null;
            rerender();

            expect(result.current.messages).toEqual([]);
            expect(result.current.activeSessionId).toBeNull();
            expect(result.current.streamingText).toBe('');
            expect(result.current.isStreaming).toBe(false);
            expect(result.current.traceSteps).toEqual([]);
            expect(result.current.citations).toEqual([]);
            expect(result.current.chatMode).toBe('normal');
            expect(result.current.activeTraceTab).toBe('rag');
            expect(result.current.isIngesting).toBe(false);
            expect(result.current.isIngestionSidebarOpen).toBe(false);
            expect(capturedSignal?.aborted).toBe(true);
        });

        it('clears local chat runtime when confirmed user A switches to B', async () => {
            mockStreamChatQuery.mockReturnValue(new AbortController());

            const { result, rerender } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            await act(async () => {
                await result.current.sendQuery('owned by A');
            });
            act(() => {
                result.current.setChatMode('web_rag');
            });
            expect(result.current.messages).toHaveLength(1);

            mockAuthState.user = { id: '2', is_superuser: false };
            rerender();

            expect(result.current.messages).toEqual([]);
            expect(result.current.chatMode).toBe('normal');
            expect(result.current.activeSessionId).toBeNull();
        });

        it('aborts active stream on identity change', async () => {
            let capturedSignal: AbortSignal | undefined;
            mockStreamChatQuery.mockImplementation((options: StreamOptions) => {
                capturedSignal = options.signal;
                return new AbortController();
            });

            const { result, rerender } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            await act(async () => {
                await result.current.sendQuery('streaming for A');
            });
            expect(capturedSignal?.aborted).toBe(false);

            mockAuthState.user = { id: '2', is_superuser: false };
            rerender();

            expect(capturedSignal?.aborted).toBe(true);
        });

        it('does not clear a fresh session when first loading from anonymous to user', async () => {
            mockAuthState.user = null;
            mockStreamChatQuery.mockReturnValue(new AbortController());

            const { result, rerender } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            // Anonymous composition has no prior confirmed identity; first login must not wipe state.
            act(() => {
                result.current.setChatMode('rag');
            });
            expect(result.current.chatMode).toBe('rag');

            mockAuthState.user = { id: '1', is_superuser: false };
            rerender();

            expect(result.current.chatMode).toBe('rag');
            expect(result.current.messages).toEqual([]);
        });

        it('anonymous normal/rag/upload do not send identity-bound requests', async () => {
            mockAuthState.user = null;
            mockStreamChatQuery.mockReturnValue(new AbortController());
            mockDefaultKbState.fetchCount = 0;
            mockSubmitRepoReadmeCheckAPI.mockClear();
            mockUploadKBFileAPI.mockClear();

            const { result } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            await act(async () => {
                await result.current.sendQuery('hello anonymous');
            });
            expect(mockStreamChatQuery).not.toHaveBeenCalled();
            expect(result.current.messages).toEqual([]);

            act(() => {
                result.current.setChatMode('rag');
            });
            await act(async () => {
                await result.current.sendQuery('rag anonymous');
            });
            expect(mockStreamChatQuery).not.toHaveBeenCalled();
            expect(mockDefaultKbState.fetchCount).toBe(0);

            const file = new File(['# hi'], 'doc.md', { type: 'text/markdown' });
            await act(async () => {
                await result.current.uploadKBFile(file);
            });
            expect(mockUploadKBFileAPI).not.toHaveBeenCalled();
            expect(result.current.isIngesting).toBe(false);
        });

        it('does not commit deferred work started before null→B login', async () => {
            // Start as A with a hanging upload, tear down to anonymous, then land as B.
            let resolveUpload: (value: {
                task_id: string;
                file_id: string;
                file_status: string;
                task_status: string;
                deduplicated: boolean;
            }) => void = () => undefined;
            mockUploadKBFileAPI.mockImplementation(
                () => new Promise((resolve) => {
                    resolveUpload = resolve;
                }),
            );

            const file = new File(['# hi'], 'doc.md', { type: 'text/markdown' });
            const { result, rerender } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            let uploadPromise: Promise<void> | undefined;
            act(() => {
                uploadPromise = result.current.uploadKBFile(file);
            });
            // mutateAsync schedules mutationFn on a microtask — flush before identity teardown.
            await act(async () => {
                await Promise.resolve();
            });
            expect(result.current.isIngesting).toBe(true);
            expect(mockUploadKBFileAPI).toHaveBeenCalled();

            mockAuthState.user = null;
            rerender();
            expect(result.current.isIngesting).toBe(false);

            mockAuthState.user = { id: '2', is_superuser: false };
            rerender();

            await act(async () => {
                resolveUpload({
                    task_id: 'task-a',
                    file_id: 'file-a',
                    file_status: 'READY',
                    task_status: 'completed',
                    deduplicated: true,
                });
                await uploadPromise;
            });

            expect(result.current.isIngesting).toBe(false);
            expect(result.current.isIngestionSidebarOpen).toBe(false);
            expect(result.current.ingestionSteps.every((step) => step.status === 'idle')).toBe(true);
        });

        it('does not commit deferred repo_check after startNewChat aborts the controller', async () => {
            let resolveSubmit: (value: { run_id: string; task_id: string; status: 'pending' }) => void =
                () => undefined;
            mockSubmitRepoReadmeCheckAPI.mockImplementation(
                () => new Promise((resolve) => {
                    resolveSubmit = resolve;
                }),
            );

            const { result } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            act(() => {
                result.current.setChatMode('repo_check');
            });

            let sendPromise: Promise<void> | undefined;
            act(() => {
                sendPromise = result.current.sendQuery('https://github.com/acme/demo');
            });
            expect(result.current.messages).toHaveLength(1);

            act(() => {
                result.current.startNewChat();
            });
            expect(result.current.messages).toEqual([]);

            await act(async () => {
                resolveSubmit({ run_id: 'run-a', task_id: 'task-a', status: 'pending' });
                await sendPromise;
            });

            expect(result.current.messages).toEqual([]);
        });

        it('does not commit deferred repo_check result after A→B', async () => {
            let resolveSubmit: (value: { run_id: string; task_id: string; status: 'pending' }) => void =
                () => undefined;
            mockSubmitRepoReadmeCheckAPI.mockImplementation(
                () => new Promise((resolve) => {
                    resolveSubmit = resolve;
                }),
            );

            const { result, rerender } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            act(() => {
                result.current.setChatMode('repo_check');
            });

            let sendPromise: Promise<void> | undefined;
            act(() => {
                sendPromise = result.current.sendQuery('https://github.com/acme/demo');
            });

            mockAuthState.user = { id: '2', is_superuser: false };
            rerender();
            expect(result.current.messages).toEqual([]);

            await act(async () => {
                resolveSubmit({ run_id: 'run-a', task_id: 'task-a', status: 'pending' });
                await sendPromise;
            });

            expect(result.current.messages).toEqual([]);
            expect(result.current.chatMode).toBe('normal');
        });

        it('does not commit deferred default-KB failure after A→B', async () => {
            let resolveKb: (value: { id: string; name: string }) => void = () => undefined;
            mockDefaultKbState.fetchCount = 0;
            mockDefaultKbState.data = undefined;
            // Override defaultKBQueryOptions path used by fetchQuery via mock state queryFn — controller uses fetchQuery(defaultKBQueryOptions()).
            // The mock queryFn is already defined; make it hang once.
            const originalFetch = mockDefaultKbState;
            void originalFetch;
            const queryClient = createTestClient();
            // Replace options by intercepting fetchQuery
            const fetchSpy = vi.spyOn(queryClient, 'fetchQuery').mockImplementation(
                () => new Promise((resolve) => {
                    resolveKb = resolve as (value: { id: string; name: string }) => void;
                }) as never,
            );

            const { result, rerender } = renderHook(() => useChatController(), {
                wrapper: createWrapper(queryClient),
            });

            act(() => {
                result.current.setChatMode('rag');
            });

            let sendPromise: Promise<void> | undefined;
            act(() => {
                sendPromise = result.current.sendQuery('rag under A');
            });

            mockAuthState.user = { id: '2', is_superuser: false };
            rerender();

            await act(async () => {
                resolveKb({ id: 'kb-a', name: 'A KB' });
                await sendPromise;
            });

            expect(result.current.messages).toEqual([]);
            expect(result.current.isStreaming).toBe(false);
            fetchSpy.mockRestore();
        });

        it('does not reopen ingestion state from deferred upload after A→B', async () => {
            let resolveUpload: (value: {
                task_id: string;
                file_id: string;
                file_status: string;
                task_status: string;
                deduplicated: boolean;
            }) => void = () => undefined;
            mockUploadKBFileAPI.mockImplementation(
                () => new Promise((resolve) => {
                    resolveUpload = resolve;
                }),
            );

            const file = new File(['# hi'], 'doc.md', { type: 'text/markdown' });
            const { result, rerender } = renderHook(() => useChatController(), {
                wrapper: createWrapper(),
            });

            let uploadPromise: Promise<void> | undefined;
            act(() => {
                uploadPromise = result.current.uploadKBFile(file);
            });
            await act(async () => {
                await Promise.resolve();
            });

            expect(result.current.isIngesting).toBe(true);
            expect(result.current.isIngestionSidebarOpen).toBe(true);
            expect(mockUploadKBFileAPI).toHaveBeenCalled();

            mockAuthState.user = { id: '2', is_superuser: false };
            rerender();
            expect(result.current.isIngesting).toBe(false);
            expect(result.current.isIngestionSidebarOpen).toBe(false);

            await act(async () => {
                resolveUpload({
                    task_id: 'task-a',
                    file_id: 'file-a',
                    file_status: 'READY',
                    task_status: 'completed',
                    deduplicated: true,
                });
                await uploadPromise;
            });

            expect(result.current.isIngesting).toBe(false);
            expect(result.current.isIngestionSidebarOpen).toBe(false);
            expect(result.current.ingestionSteps.every((step) => step.status === 'idle' || step.status === 'done' || step.status === 'error' || step.status === 'running' || step.status === 'skipped')).toBe(true);
            // After identity reset, steps are re-initialized to idle ingestion steps.
            expect(result.current.ingestionSteps.every((step) => step.status === 'idle')).toBe(true);
        });
    });
});
