import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSessionDetailQuery } from '../../query/hooks/chat';
import type { ChatMessage, ChatSession, SessionDetailResponse } from '../../types/chat';

export type UseChatSessionStateReturn = {
  activeSessionId: string | null;
  /** Displayed session (detail when in history mode with data). */
  activeSession: ChatSession | null;
  /** Live local messages (hydrated from history detail for continue-chat). */
  messages: ChatMessage[];
  displayedMessages: ChatMessage[];
  isSessionFromHistory: boolean;
  isLoadingHistory: boolean;
  sessionDetailData: SessionDetailResponse | undefined;
  selectSession: (session: ChatSession) => void;
  enterLiveMode: () => void;
  appendMessage: (message: ChatMessage) => void;
  updateMessages: (updater: (prev: ChatMessage[]) => ChatMessage[]) => void;
  commitSession: (session: ChatSession) => void;
  resetSession: () => void;
};

/**
 * Active session, messages, history selection, and detail hydration.
 * Stream / facade write only through commands — no raw setters exposed.
 */
export function useChatSessionState(): UseChatSessionStateReturn {
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [activeSession, setActiveSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSessionFromHistory, setIsSessionFromHistory] = useState(false);

  const detailSessionId = isSessionFromHistory ? activeSessionId : null;
  const { data: sessionDetailData, isLoading: detailLoading } =
    useSessionDetailQuery(detailSessionId);

  const isLoadingHistory = detailLoading && isSessionFromHistory;

  const displayedActiveSession =
    isSessionFromHistory && sessionDetailData
      ? sessionDetailData.session
      : activeSession;

  const displayedMessages = useMemo(
    () =>
      isSessionFromHistory && sessionDetailData
        ? sessionDetailData.messages || []
        : messages,
    [isSessionFromHistory, sessionDetailData, messages],
  );

  // Hydrate live messages from history detail so continue-chat can enter live mode.
  // Mode / trace / citation stay in the controller facade.
  useEffect(() => {
    if (!isSessionFromHistory || !sessionDetailData) return;
    // Historical session selection hydrates local chat state from query data.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate live state from detail Query
    setMessages(sessionDetailData.messages || []);
  }, [isSessionFromHistory, sessionDetailData]);

  const selectSession = useCallback((session: ChatSession) => {
    // Idempotent when already viewing this history session — avoid wiping live
    // messages while detail hydration will not re-fire (same id + flag + data).
    if (isSessionFromHistory && activeSessionId === session.id) {
      return;
    }
    setIsSessionFromHistory(true);
    setActiveSessionId(session.id);
    setActiveSession(session);
    setMessages([]);
  }, [activeSessionId, isSessionFromHistory]);

  const enterLiveMode = useCallback(() => {
    setIsSessionFromHistory(false);
  }, []);

  const appendMessage = useCallback((message: ChatMessage) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  const updateMessages = useCallback(
    (updater: (prev: ChatMessage[]) => ChatMessage[]) => {
      setMessages(updater);
    },
    [],
  );

  const commitSession = useCallback((session: ChatSession) => {
    setActiveSessionId(session.id);
    setActiveSession(session);
  }, []);

  const resetSession = useCallback(() => {
    setIsSessionFromHistory(false);
    setActiveSessionId(null);
    setActiveSession(null);
    setMessages([]);
  }, []);

  return {
    activeSessionId,
    activeSession: displayedActiveSession,
    messages,
    displayedMessages,
    isSessionFromHistory,
    isLoadingHistory,
    sessionDetailData,
    selectSession,
    enterLiveMode,
    appendMessage,
    updateMessages,
    commitSession,
    resetSession,
  };
}
