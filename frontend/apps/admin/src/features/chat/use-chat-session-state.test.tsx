import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import type { SessionDetailResponse } from '../../types/chat';
import { useChatSessionState } from './use-chat-session-state';

let mockSessionDetailData: { data?: SessionDetailResponse; isLoading: boolean } = {
  data: undefined,
  isLoading: false,
};

vi.mock('../../query/hooks/chat', () => ({
  useSessionDetailQuery: (sessionId: string | null) => {
    if (!sessionId) {
      return { data: undefined, isLoading: false };
    }
    return mockSessionDetailData;
  },
}));

const baseSession = {
  id: 'hist-1',
  title: 'History',
  user_id: '1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  total_tokens: 50,
};

const historicalDetail: SessionDetailResponse = {
  session: { ...baseSession, kb_id: 'kb-1' },
  messages: [
    {
      id: 'h-m1',
      session_id: 'hist-1',
      role: 'user',
      content: 'old question',
      status: 'success',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 'h-m2',
      session_id: 'hist-1',
      role: 'assistant',
      content: 'old answer',
      status: 'success',
      created_at: '2026-01-01T00:00:01Z',
      updated_at: '2026-01-01T00:00:01Z',
    },
  ],
  total_messages: 2,
};

beforeEach(() => {
  mockSessionDetailData = { data: undefined, isLoading: false };
});

describe('useChatSessionState', () => {
  it('selectSession enters history mode, shows loading, and clears live messages', () => {
    mockSessionDetailData = { data: undefined, isLoading: true };

    const { result } = renderHook(() => useChatSessionState());

    act(() => {
      result.current.appendMessage({
        id: 'live-1',
        session_id: 's-live',
        role: 'user',
        content: 'prior live message',
        status: 'success',
        created_at: '',
        updated_at: '',
      });
    });
    expect(result.current.messages).toHaveLength(1);

    act(() => {
      result.current.selectSession(baseSession);
    });

    expect(result.current.isSessionFromHistory).toBe(true);
    expect(result.current.activeSessionId).toBe('hist-1');
    expect(result.current.isLoadingHistory).toBe(true);
    expect(result.current.displayedMessages).toEqual([]);
    expect(result.current.messages).toEqual([]);
  });

  it('selectSession is a no-op when the same history session is selected again', () => {
    const { result, rerender } = renderHook(() => useChatSessionState());

    act(() => {
      result.current.selectSession(baseSession);
    });
    act(() => {
      mockSessionDetailData = { data: historicalDetail, isLoading: false };
      rerender();
    });

    expect(result.current.messages).toHaveLength(2);

    act(() => {
      result.current.selectSession(baseSession);
    });

    // Must not wipe hydrated live messages (detail effect will not re-fire).
    expect(result.current.isSessionFromHistory).toBe(true);
    expect(result.current.activeSessionId).toBe('hist-1');
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.displayedMessages).toHaveLength(2);
  });

  it('shows detail session/messages when history detail arrives and hydrates live messages', () => {
    const { result, rerender } = renderHook(() => useChatSessionState());

    act(() => {
      result.current.selectSession(baseSession);
    });

    act(() => {
      mockSessionDetailData = { data: historicalDetail, isLoading: false };
      rerender();
    });

    expect(result.current.isLoadingHistory).toBe(false);
    expect(result.current.activeSession).toEqual(historicalDetail.session);
    expect(result.current.displayedMessages).toHaveLength(2);
    expect(result.current.displayedMessages[0].content).toBe('old question');
    // Live messages hydrated for continue-chat.
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1].content).toBe('old answer');
  });

  it('enterLiveMode uses hydrated live messages after leaving history display', () => {
    const { result, rerender } = renderHook(() => useChatSessionState());

    act(() => {
      result.current.selectSession(baseSession);
    });
    act(() => {
      mockSessionDetailData = { data: historicalDetail, isLoading: false };
      rerender();
    });

    act(() => {
      result.current.enterLiveMode();
    });

    expect(result.current.isSessionFromHistory).toBe(false);
    expect(result.current.isLoadingHistory).toBe(false);
    // Displayed falls back to live messages (hydrated copy).
    expect(result.current.displayedMessages).toHaveLength(2);
    expect(result.current.displayedMessages[0].content).toBe('old question');
    expect(result.current.activeSession).toEqual(baseSession);
  });

  it('appendMessage and updateMessages mutate live state', () => {
    const { result } = renderHook(() => useChatSessionState());

    act(() => {
      result.current.appendMessage({
        id: 'm1',
        session_id: 's1',
        role: 'user',
        content: 'hello',
        status: 'success',
        created_at: '',
        updated_at: '',
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.displayedMessages[0].content).toBe('hello');

    act(() => {
      result.current.updateMessages((prev) =>
        prev.map((msg) =>
          msg.id === 'm1' ? { ...msg, content: 'hello world' } : msg,
        ),
      );
    });

    expect(result.current.messages[0].content).toBe('hello world');
  });

  it('commitSession updates live session id and metadata', () => {
    const { result } = renderHook(() => useChatSessionState());

    act(() => {
      result.current.commitSession({
        id: 's-new',
        title: 'New chat',
        user_id: '1',
        kb_id: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        total_tokens: 0,
      });
    });

    expect(result.current.activeSessionId).toBe('s-new');
    expect(result.current.activeSession?.title).toBe('New chat');
    expect(result.current.isSessionFromHistory).toBe(false);
  });

  it('resetSession clears session, messages, and history flag', () => {
    const { result, rerender } = renderHook(() => useChatSessionState());

    act(() => {
      result.current.selectSession(baseSession);
    });
    act(() => {
      mockSessionDetailData = { data: historicalDetail, isLoading: false };
      rerender();
    });
    act(() => {
      result.current.appendMessage({
        id: 'extra',
        session_id: 'hist-1',
        role: 'user',
        content: 'extra',
        status: 'success',
        created_at: '',
        updated_at: '',
      });
    });

    act(() => {
      result.current.resetSession();
    });

    expect(result.current.activeSessionId).toBeNull();
    expect(result.current.activeSession).toBeNull();
    expect(result.current.messages).toEqual([]);
    expect(result.current.displayedMessages).toEqual([]);
    expect(result.current.isSessionFromHistory).toBe(false);
    expect(result.current.isLoadingHistory).toBe(false);
  });
});
