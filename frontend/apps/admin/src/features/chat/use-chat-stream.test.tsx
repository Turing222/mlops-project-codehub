import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type {
  RetryStreamOptions,
  StreamCallbacks,
  StreamOptions,
} from '../../streams/chat-stream';
import type { ChatMessage } from '../../types/chat';
import {
  useChatStream,
  type SessionStreamActions,
  type TraceStreamActions,
  type UseChatStreamParams,
} from './use-chat-stream';

vi.mock('../../streams/chat-stream', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../streams/chat-stream')>()),
  streamChatQuery: vi.fn(),
  streamChatRetry: vi.fn(),
}));

vi.mock('../../api/chat', () => ({
  getSessionDetailAPI: vi.fn().mockResolvedValue({
    session: { id: 's1', title: 'T', user_id: '1', created_at: '', updated_at: '', total_tokens: 0 },
    messages: [],
    total_messages: 0,
  }),
  getGenerationRequestAPI: vi.fn(),
  resolveGenerationRequestAPI: vi.fn(),
}));

vi.mock('../../api/repo-analysis', () => ({
  submitRepoReadmeCheckAPI: vi.fn(),
}));

import { streamChatQuery, streamChatRetry } from '../../streams/chat-stream';
import {
  getSessionDetailAPI,
  getGenerationRequestAPI,
  resolveGenerationRequestAPI,
} from '../../api/chat';
import { submitRepoReadmeCheckAPI } from '../../api/repo-analysis';

const mockStreamChatQuery = vi.mocked(streamChatQuery);
const mockStreamChatRetry = vi.mocked(streamChatRetry);
const mockGetSessionDetail = vi.mocked(getSessionDetailAPI);
const mockGetGenerationRequest = vi.mocked(getGenerationRequestAPI);
const mockResolveGenerationRequest = vi.mocked(resolveGenerationRequestAPI);
const mockSubmitRepo = vi.mocked(submitRepoReadmeCheckAPI);

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function createSessionActions(overrides: Partial<SessionStreamActions> = {}) {
  const messages: ChatMessage[] = [];
  const actions: SessionStreamActions = {
    enterLiveMode: vi.fn(),
    appendMessage: vi.fn((msg: ChatMessage) => {
      messages.push(msg);
    }),
    updateMessages: vi.fn((updater) => {
      const next = updater([...messages]);
      messages.length = 0;
      messages.push(...next);
    }),
    commitSession: vi.fn(),
    ...overrides,
  };
  return { actions, messages };
}

function createTraceActions(overrides: Partial<TraceStreamActions> = {}): TraceStreamActions {
  return {
    reset: vi.fn(),
    markNetworkStarted: vi.fn(),
    applyMetaSkips: vi.fn(),
    handleStep: vi.fn(),
    completeIdle: vi.fn(),
    markError: vi.fn(),
    applyDetailFromAssistant: vi.fn(),
    ...overrides,
  };
}

function baseParams(
  partial: Partial<UseChatStreamParams> & {
    sessionActions: SessionStreamActions;
    traceActions: TraceStreamActions;
  },
): UseChatStreamParams {
  return {
    userId: '1',
    refreshUser: vi.fn().mockResolvedValue(undefined),
    chatMode: 'normal',
    activeSessionId: null,
    displayedMessages: [],
    resolveDefaultKbId: vi.fn().mockResolvedValue('kb1'),
    explicitRetryEnabled: false,
    ...partial,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetSessionDetail.mockResolvedValue({
    session: { id: 's1', title: 'T', user_id: '1', created_at: '', updated_at: '', total_tokens: 0 },
    messages: [],
    total_messages: 0,
  });
  mockStreamChatQuery.mockReturnValue(new AbortController());
  mockStreamChatRetry.mockReturnValue(new AbortController());
  mockGetGenerationRequest.mockRejectedValue(new Error('not found'));
  mockResolveGenerationRequest.mockRejectedValue(new Error('not found'));
});

describe('useChatStream', () => {
  it('aborts previous stream signal when sending a new query', async () => {
    let firstSignal: AbortSignal | undefined;
    mockStreamChatQuery.mockImplementation((options: StreamOptions) => {
      if (!firstSignal) firstSignal = options.signal;
      return new AbortController();
    });

    const { actions } = createSessionActions();
    const { result } = renderHook(
      () => useChatStream(baseParams({
        sessionActions: actions,
        traceActions: createTraceActions(),
      })),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.sendQuery('first');
    });
    expect(firstSignal?.aborted).toBe(false);

    await act(async () => {
      await result.current.sendQuery('second');
    });
    expect(firstSignal?.aborted).toBe(true);
  });

  it('does not commit onDone/onError after abort', async () => {
    let callbacks: Partial<StreamCallbacks> = {};
    mockStreamChatQuery.mockImplementation((_o: StreamOptions, cb: StreamCallbacks) => {
      callbacks = cb;
      return new AbortController();
    });

    const { actions, messages } = createSessionActions();
    const trace = createTraceActions();
    const { result } = renderHook(
      () => useChatStream(baseParams({ sessionActions: actions, traceActions: trace })),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.sendQuery('q');
    });
    act(() => {
      result.current.resetStream();
    });

    const before = messages.length;
    act(() => {
      callbacks.onDone!();
    });
    expect(messages.length).toBe(before);

    act(() => {
      callbacks.onError!(new Error('late'));
    });
    expect(messages.length).toBe(before);
    expect(trace.completeIdle).not.toHaveBeenCalled();
    expect(trace.markError).not.toHaveBeenCalled();
  });

  it('invokes session and trace actions for meta/chunk/step/done/error', async () => {
    let callbacks: Partial<StreamCallbacks> = {};
    mockStreamChatQuery.mockImplementation((_o: StreamOptions, cb: StreamCallbacks) => {
      callbacks = cb;
      return new AbortController();
    });

    const { actions } = createSessionActions();
    const trace = createTraceActions();
    const { result } = renderHook(
      () => useChatStream(baseParams({ sessionActions: actions, traceActions: trace })),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.sendQuery('hello');
    });

    expect(actions.enterLiveMode).toHaveBeenCalled();
    expect(actions.appendMessage).toHaveBeenCalled();
    expect(trace.reset).toHaveBeenCalled();

    act(() => {
      callbacks.onStarted?.({ type: 'started' } as never);
      callbacks.onMeta!({
        type: 'meta',
        session_id: 's1',
        session_title: 'T',
        message_id: 'm1',
      });
      callbacks.onStep?.({
        type: 'step',
        step: 'kb-search',
        status: 'running',
      } as never);
      callbacks.onChunk!({ type: 'chunk', content: 'hi' });
    });

    expect(trace.markNetworkStarted).toHaveBeenCalled();
    expect(trace.applyMetaSkips).toHaveBeenCalledWith('normal');
    expect(actions.commitSession).toHaveBeenCalled();
    expect(trace.handleStep).toHaveBeenCalled();
    expect(result.current.streamingText).toBe('hi');

    await act(async () => {
      callbacks.onDone!();
    });
    expect(trace.completeIdle).toHaveBeenCalled();
    expect(result.current.isStreaming).toBe(false);
  });

  it('passes kbId for rag and enableExternalContext for web_rag', async () => {
    const captured: StreamOptions[] = [];
    mockStreamChatQuery.mockImplementation((options: StreamOptions) => {
      captured.push(options);
      return new AbortController();
    });

    const { actions } = createSessionActions();
    const { result, rerender } = renderHook(
      (props: { mode: 'rag' | 'web_rag' | 'normal' }) =>
        useChatStream(baseParams({
          chatMode: props.mode,
          sessionActions: actions,
          traceActions: createTraceActions(),
          resolveDefaultKbId: async () => 'kb-default',
        })),
      {
        wrapper: createWrapper(),
        initialProps: { mode: 'rag' as 'rag' | 'web_rag' | 'normal' },
      },
    );

    await act(async () => {
      await result.current.sendQuery('rag q');
    });
    expect(captured[0].kbId).toBe('kb-default');
    expect(captured[0].enableExternalContext).toBe(false);

    rerender({ mode: 'web_rag' });
    await act(async () => {
      await result.current.sendQuery('web q');
    });
    expect(captured[1].kbId).toBe('kb-default');
    expect(captured[1].enableExternalContext).toBe(true);

    rerender({ mode: 'normal' });
    await act(async () => {
      await result.current.sendQuery('n');
    });
    expect(captured[2].kbId).toBeUndefined();
    expect(captured[2].enableExternalContext).toBe(false);
  });

  it('repo_check early-returns without streamChatQuery', async () => {
    mockSubmitRepo.mockResolvedValue({ run_id: 'run-1' } as never);
    const { actions } = createSessionActions();
    const { result } = renderHook(
      () => useChatStream(baseParams({
        chatMode: 'repo_check',
        sessionActions: actions,
        traceActions: createTraceActions(),
      })),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.sendQuery('https://github.com/a/b');
    });

    expect(mockStreamChatQuery).not.toHaveBeenCalled();
    expect(mockSubmitRepo).toHaveBeenCalled();
    expect(actions.appendMessage).toHaveBeenCalledTimes(2);
  });

  it('fails closed when a pre-meta error identity cannot be resolved', async () => {
    mockStreamChatQuery.mockImplementation((_options, callbacks) => {
      callbacks.onError(new Error('fail'));
      return new AbortController();
    });
    const { actions, messages } = createSessionActions();
    const { result } = renderHook(
      () => useChatStream(baseParams({
        sessionActions: actions,
        traceActions: createTraceActions(),
        displayedMessages: messages,
        explicitRetryEnabled: true,
      })),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.sendQuery('query one');
    });
    await vi.waitFor(() => {
      expect(messages.some((message) => message.status === 'failed')).toBe(true);
    });
    const failedMessage = messages.find((message) => message.status === 'failed')!;

    act(() => result.current.retryFailedMessage(failedMessage.id));

    expect(failedMessage.retryable).toBe(false);
    expect(mockResolveGenerationRequest).toHaveBeenCalledOnce();
    expect(mockStreamChatRetry).not.toHaveBeenCalled();
  });

  it('shows an accepted request as still running instead of retryable failure', async () => {
    let callbacks: Partial<StreamCallbacks> = {};
    mockStreamChatQuery.mockImplementation((_options, streamCallbacks) => {
      callbacks = streamCallbacks;
      return new AbortController();
    });
    mockResolveGenerationRequest.mockResolvedValue({
      generation_request_id: 'request-running',
      client_request_id: 'client-running',
      session_id: 's1',
      assistant_message_id: 'a-running',
      status: 'running',
      attempt: 1,
      retryable: false,
      error_code: null,
      error_message: null,
      created_at: '2026-07-17T00:00:00Z',
      updated_at: '2026-07-17T00:00:01Z',
      finished_at: null,
    });
    const { actions, messages } = createSessionActions();
    const { result } = renderHook(
      () => useChatStream(baseParams({
        sessionActions: actions,
        traceActions: createTraceActions(),
        displayedMessages: messages,
        explicitRetryEnabled: true,
      })),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.sendQuery('still running');
      callbacks.onError?.(new Error('stream disconnected'));
    });

    await vi.waitFor(() => {
      expect(messages.find((message) => message.id === 'a-running')).toMatchObject({
        status: 'failed',
        retryable: false,
        error_code: 'CHAT_REQUEST_STILL_RUNNING',
        content: expect.stringContaining('仍在生成中'),
      });
    });
  });

  it('hydrates the completed message when transport fails after settlement', async () => {
    let callbacks: Partial<StreamCallbacks> = {};
    mockStreamChatQuery.mockImplementation((_options, streamCallbacks) => {
      callbacks = streamCallbacks;
      return new AbortController();
    });
    mockResolveGenerationRequest.mockResolvedValue({
      generation_request_id: 'request-succeeded',
      client_request_id: 'client-succeeded',
      session_id: 's1',
      assistant_message_id: 'a-succeeded',
      status: 'succeeded',
      attempt: 1,
      retryable: false,
      error_code: null,
      error_message: null,
      created_at: '2026-07-17T00:00:00Z',
      updated_at: '2026-07-17T00:00:01Z',
      finished_at: '2026-07-17T00:00:01Z',
    });
    mockGetSessionDetail.mockResolvedValue({
      session: {
        id: 's1',
        title: 'T',
        user_id: '1',
        created_at: '',
        updated_at: '',
        total_tokens: 0,
      },
      messages: [tempAssistant('a-succeeded', 'settled answer', 'success')],
      total_messages: 1,
    });
    const { actions, messages } = createSessionActions();
    const trace = createTraceActions();
    const { result } = renderHook(
      () => useChatStream(baseParams({
        sessionActions: actions,
        traceActions: trace,
        displayedMessages: messages,
      })),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.sendQuery('already settled');
      callbacks.onError?.(new Error('stream disconnected'));
    });

    await vi.waitFor(() => {
      expect(messages).toEqual([
        expect.objectContaining({
          id: 'a-succeeded',
          status: 'success',
          content: 'settled answer',
        }),
      ]);
    });
    expect(trace.completeIdle).toHaveBeenCalled();
    expect(trace.markError).not.toHaveBeenCalled();
  });

  it('retries only with server generation identity and expected attempt', async () => {
    const { actions, messages } = createSessionActions();
    messages.push(
      tempUser('u1', 'from history'),
      {
        ...tempAssistant('a1', 'failed', 'failed'),
        generation_request_id: 'request-1',
        attempt: 3,
        retryable: true,
        error_code: 'CHAT_GENERATION_FAILED',
      },
    );
    mockGetSessionDetail.mockResolvedValue({
      session: {
        id: 's1',
        title: 'T',
        user_id: '1',
        created_at: '',
        updated_at: '',
        total_tokens: 0,
      },
      messages: [{
        ...tempAssistant('a1', 'recovered', 'success'),
        generation_request_id: 'request-1',
        attempt: 4,
        retryable: false,
      }],
      total_messages: 1,
    });
    let retryCallbacks: StreamCallbacks | undefined;
    const captured: RetryStreamOptions[] = [];
    mockStreamChatRetry.mockImplementation((options, callbacks) => {
      captured.push(options);
      retryCallbacks = callbacks;
      return new AbortController();
    });
    const { result } = renderHook(
      () => useChatStream(baseParams({
        activeSessionId: 's1',
        sessionActions: actions,
        traceActions: createTraceActions(),
        displayedMessages: messages,
        explicitRetryEnabled: true,
      })),
      { wrapper: createWrapper() },
    );

    act(() => result.current.retryFailedMessage('a1'));

    expect(captured).toEqual([expect.objectContaining({
      generationRequestId: 'request-1',
      expectedAttempt: 3,
      sessionId: 's1',
    })]);
    expect(mockStreamChatQuery).not.toHaveBeenCalled();

    await act(async () => {
      retryCallbacks?.onMeta({
        type: 'meta',
        session_id: 's1',
        session_title: 'T',
        message_id: 'a1',
        generation_request_id: 'request-1',
        attempt: 4,
      });
      retryCallbacks?.onChunk({ type: 'chunk', content: 'recovered' });
      retryCallbacks?.onDone();
    });
    expect(messages.find((message) => message.id === 'a1')).toMatchObject({
      status: 'success',
      content: 'recovered',
      attempt: 4,
      retryable: false,
    });
  });

  it('resetStream aborts and clears streaming state', async () => {
    let signal: AbortSignal | undefined;
    mockStreamChatQuery.mockImplementation((options: StreamOptions) => {
      signal = options.signal;
      return new AbortController();
    });

    const { actions } = createSessionActions();
    const { result } = renderHook(
      () => useChatStream(baseParams({ sessionActions: actions, traceActions: createTraceActions() })),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.sendQuery('q');
    });
    expect(result.current.isStreaming).toBe(true);

    act(() => {
      result.current.resetStream();
    });
    expect(signal?.aborted).toBe(true);
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.streamingText).toBe('');
  });

  it('unmount aborts the stream and ignores late callbacks', async () => {
    let signal: AbortSignal | undefined;
    let callbacks: Partial<StreamCallbacks> = {};
    mockStreamChatQuery.mockImplementation((options: StreamOptions, cb: StreamCallbacks) => {
      signal = options.signal;
      callbacks = cb;
      return new AbortController();
    });

    const { actions } = createSessionActions();
    const trace = createTraceActions();
    const { result, unmount } = renderHook(
      () => useChatStream(baseParams({ sessionActions: actions, traceActions: trace })),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.sendQuery('q');
    });
    const appendCountBefore = vi.mocked(actions.appendMessage).mock.calls.length;

    act(() => {
      unmount();
    });
    expect(signal?.aborted).toBe(true);

    act(() => {
      callbacks.onChunk!({ type: 'chunk', content: 'late' });
      callbacks.onDone!();
      callbacks.onError!(new Error('late'));
    });

    expect(vi.mocked(actions.appendMessage).mock.calls.length).toBe(appendCountBefore);
    expect(trace.completeIdle).not.toHaveBeenCalled();
    expect(trace.markError).not.toHaveBeenCalled();
  });
});

function tempUser(id: string, content: string): ChatMessage {
  return {
    id,
    session_id: 's1',
    role: 'user',
    content,
    status: 'success',
    created_at: '',
    updated_at: '',
  };
}

function tempAssistant(
  id: string,
  content: string,
  status: 'success' | 'failed',
): ChatMessage {
  return {
    id,
    session_id: 's1',
    role: 'assistant',
    content,
    status,
    created_at: '',
    updated_at: '',
  };
}

afterEach(() => {
  vi.useRealTimers();
});
