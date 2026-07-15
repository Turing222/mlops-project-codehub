import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type { StreamCallbacks, StreamOptions } from '../../streams/chat-stream';
import type { ChatMessage } from '../../types/chat';
import {
  useChatStream,
  type SessionStreamActions,
  type TraceStreamActions,
  type UseChatStreamParams,
} from './use-chat-stream';

vi.mock('../../streams/chat-stream', () => ({
  streamChatQuery: vi.fn(),
}));

vi.mock('../../api/chat', () => ({
  getSessionDetailAPI: vi.fn().mockResolvedValue({
    session: { id: 's1', title: 'T', user_id: '1', created_at: '', updated_at: '', total_tokens: 0 },
    messages: [],
    total_messages: 0,
  }),
}));

vi.mock('../../api/repo-analysis', () => ({
  submitRepoReadmeCheckAPI: vi.fn(),
}));

import { streamChatQuery } from '../../streams/chat-stream';
import { submitRepoReadmeCheckAPI } from '../../api/repo-analysis';

const mockStreamChatQuery = vi.mocked(streamChatQuery);
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
    ...partial,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockStreamChatQuery.mockReturnValue(new AbortController());
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

  it('retry cache hit reuses clientRequestId; miss uses prior user message', async () => {
    const captured: StreamOptions[] = [];
    mockStreamChatQuery.mockImplementation((options: StreamOptions, cb: StreamCallbacks) => {
      captured.push(options);
      cb.onError!(new Error('fail'));
      return new AbortController();
    });

    const { actions, messages } = createSessionActions();
    const { result } = renderHook(
      () => useChatStream(baseParams({ sessionActions: actions, traceActions: createTraceActions() })),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.sendQuery('query one');
    });
    const failedId = messages.find((m) => m.status === 'failed')!.id;
    const firstId = captured[0].clientRequestId;

    await act(async () => {
      result.current.retryFailedMessage(failedId);
    });
    expect(captured[1].clientRequestId).toBe(firstId);
    expect(captured[1].query).toBe('query one');
  });

  it('TTL-expired retry cache falls back to message history without reusing clientRequestId', async () => {
    vi.useFakeTimers();
    const now = Date.now();
    vi.setSystemTime(now);

    const captured: StreamOptions[] = [];
    let callbacks: Partial<StreamCallbacks> = {};
    mockStreamChatQuery.mockImplementation((options: StreamOptions, cb: StreamCallbacks) => {
      captured.push(options);
      callbacks = cb;
      return new AbortController();
    });

    const { actions, messages } = createSessionActions();
    const { result, rerender } = renderHook(
      (props: { displayed: ChatMessage[] }) =>
        useChatStream(baseParams({
          sessionActions: actions,
          traceActions: createTraceActions(),
          displayedMessages: props.displayed,
        })),
      { wrapper: createWrapper(), initialProps: { displayed: [] as ChatMessage[] } },
    );

    await act(async () => {
      await result.current.sendQuery('cached query');
    });
    act(() => {
      callbacks.onError!(new Error('boom'));
    });

    const failedId = messages.find((m) => m.status === 'failed')!.id;
    const originalClientId = captured[0].clientRequestId;
    expect(originalClientId).toBeDefined();

    // History fallback list must include the same failed id after cache TTL prune.
    await act(async () => {
      rerender({
        displayed: [
          tempUser('u1', 'from history'),
          tempAssistant(failedId, 'failed', 'failed'),
        ],
      });
    });

    // Expire retry cache (5 min TTL) so the same id is a cache miss.
    vi.setSystemTime(now + 6 * 60 * 1000);

    await act(async () => {
      result.current.retryFailedMessage(failedId);
    });

    expect(captured).toHaveLength(2);
    expect(captured[1].query).toBe('from history');
    expect(captured[1].clientRequestId).not.toBe(originalClientId);
    vi.useRealTimers();
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
