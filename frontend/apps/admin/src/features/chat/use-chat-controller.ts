import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../context/useAuth';
import { defaultKBQueryOptions, useDefaultKBQuery } from '../../query/hooks/knowledge';
import { useKbIngestion } from '../knowledge/use-kb-ingestion';
import { useChatSessionState } from './use-chat-session-state';
import {
  useChatStream,
  type ChatMode,
  type SendMessageOptions,
  type TraceStreamActions,
} from './use-chat-stream';
import {
  advanceTraceToStep,
  applyMetaModeSkips,
  applyStreamStepEvent,
  completeIdleTraceSteps,
  deriveAssistantDetailPresentation,
  deriveHistoryPresentation,
  markReceiveQueryNetwork,
  markRunningTraceError,
} from './chat-trace-steps';
import type { ChatMessage, ChatSession } from '../../types/chat';
import { createInitialTraceSteps } from '../../types/agent-trace';
import type { AgentTraceStep, CitationItem } from '../../types/agent-trace';

export type { ChatMode, SendMessageOptions };

export type UseChatControllerReturn = {
  activeSessionId: string | null;
  activeSession: ChatSession | null;
  messages: ChatMessage[];
  streamingText: string;
  isStreaming: boolean;
  isLoadingHistory: boolean;
  sendQuery: (text: string, options?: SendMessageOptions) => Promise<void>;
  retryFailedMessage: (messageId: string) => void;
  selectSession: (session: ChatSession) => void;
  startNewChat: () => void;
  traceSteps: AgentTraceStep[];
  citations: CitationItem[];
  chatMode: ChatMode;
  setChatMode: (mode: ChatMode) => void;
  activeTraceTab: 'rag' | 'ingestion';
  setActiveTraceTab: (tab: 'rag' | 'ingestion') => void;
  ingestionSteps: AgentTraceStep[];
  uploadKBFile: (file: File) => Promise<void>;
  isIngesting: boolean;
  isIngestionSidebarOpen: boolean;
  setIsIngestionSidebarOpen: (open: boolean) => void;
};

export function useChatController(): UseChatControllerReturn {
  const { user, refreshUser } = useAuth();
  const queryClient = useQueryClient();

  const {
    activeSessionId,
    activeSession,
    displayedMessages,
    isSessionFromHistory,
    isLoadingHistory,
    sessionDetailData,
    selectSession: selectSessionState,
    enterLiveMode,
    appendMessage,
    updateMessages,
    commitSession,
    resetSession,
  } = useChatSessionState();

  const [traceSteps, setTraceSteps] = useState<AgentTraceStep[]>([]);
  const [citations, setCitations] = useState<CitationItem[]>([]);
  const [chatMode, setChatMode] = useState<ChatMode>('normal');

  const {
    activeTraceTab,
    setActiveTraceTab,
    ingestionSteps,
    uploadKBFile,
    isIngesting,
    isIngestionSidebarOpen,
    setIsIngestionSidebarOpen,
    resetIngestion,
  } = useKbIngestion({ userId: user?.id != null ? String(user.id) : null });

  const { data: defaultKb } = useDefaultKBQuery({ enabled: false });

  // eslint-disable-next-line react-hooks/preserve-manual-memoization -- fetchQuery closure over user/defaultKb
  const resolveDefaultKbId = useCallback(async (): Promise<string | null> => {
    if (!user?.id) return null;
    if (defaultKb?.id) return defaultKb.id;
    try {
      return (await queryClient.fetchQuery(defaultKBQueryOptions())).id;
    } catch (err) {
      console.error('获取默认知识库失败:', err);
      return null;
    }
  }, [defaultKb?.id, queryClient, user?.id]);

  const lastConfirmedUserIdRef = useRef<string | null>(null);

  const traceActions: TraceStreamActions = useMemo(() => ({
    reset() {
      setTraceSteps(createInitialTraceSteps());
      setCitations([]);
    },
    markNetworkStarted(networkMs) {
      setTraceSteps((prev) => markReceiveQueryNetwork(prev, networkMs));
    },
    applyMetaSkips(mode) {
      setTraceSteps((prev) => applyMetaModeSkips(prev, mode));
    },
    handleStep(event) {
      setTraceSteps((prev) => {
        const next = applyStreamStepEvent(prev, event);
        return event.status === 'running' ? advanceTraceToStep(next, event.step) : next;
      });
    },
    completeIdle() {
      setTraceSteps(completeIdleTraceSteps);
    },
    markError() {
      setTraceSteps(markRunningTraceError);
    },
    applyDetailFromAssistant(lastAssistant, session) {
      const derived = deriveAssistantDetailPresentation(lastAssistant, session);
      if (derived.chatMode) setChatMode(derived.chatMode);
      setCitations(derived.citations);
      setTraceSteps(derived.applyMetrics);
    },
  }), []);

  const sessionActions = useMemo(() => ({
    enterLiveMode,
    appendMessage,
    updateMessages,
    commitSession,
  }), [enterLiveMode, appendMessage, updateMessages, commitSession]);

  const {
    streamingText,
    isStreaming,
    sendQuery,
    retryFailedMessage,
    abort,
    resetStream,
  } = useChatStream({
    userId: user?.id != null ? String(user.id) : null,
    refreshUser,
    chatMode,
    activeSessionId,
    displayedMessages,
    sessionActions,
    traceActions,
    resolveDefaultKbId,
  });

  const resetChatSessionState = useCallback(() => {
    resetStream();
    resetSession();
    setChatMode('normal');
    setTraceSteps([]);
    setCitations([]);
  }, [resetSession, resetStream]);

  const resetIdentityRuntime = useCallback(() => {
    resetChatSessionState();
    resetIngestion();
  }, [resetChatSessionState, resetIngestion]);

  // A→null/A→B: full reset. null→B: abort stream + ingestion, keep empty session UI.
  useEffect(() => {
    const nextUserId = user?.id != null ? String(user.id) : null;
    const previousUserId = lastConfirmedUserIdRef.current;
    if (previousUserId !== null && previousUserId !== nextUserId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- identity boundary
      resetIdentityRuntime();
    } else if (previousUserId === null && nextUserId !== null) {
      abort();
      resetIngestion();
    }
    lastConfirmedUserIdRef.current = nextUserId;
  }, [user?.id, resetIdentityRuntime, resetIngestion, abort]);

  // History detail: mode / trace / citation (messages hydrate in session hook).
  useEffect(() => {
    if (!isSessionFromHistory || !sessionDetailData) return;
    const derived = deriveHistoryPresentation(sessionDetailData);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate from detail
    setChatMode(derived.chatMode);
    setCitations(derived.citations);
    setTraceSteps(derived.applyMetrics);
  }, [isSessionFromHistory, sessionDetailData]);

  const selectSession = useCallback((session: ChatSession) => {
    // Same history session re-click: keep hydrated state (effects would not re-fire).
    if (isSessionFromHistory && activeSessionId === session.id) return;
    // Abort in-flight stream / pending detail so old callbacks cannot write the new session.
    resetStream();
    selectSessionState(session);
    setChatMode(session.kb_id ? 'rag' : 'normal');
    setTraceSteps([]);
    setCitations([]);
  }, [activeSessionId, isSessionFromHistory, resetStream, selectSessionState]);

  const startNewChat = useCallback(() => {
    resetChatSessionState();
  }, [resetChatSessionState]);

  return {
    activeSessionId,
    activeSession,
    messages: displayedMessages,
    streamingText,
    isStreaming,
    isLoadingHistory,
    sendQuery,
    retryFailedMessage,
    selectSession,
    startNewChat,
    traceSteps,
    citations,
    chatMode,
    setChatMode,
    activeTraceTab,
    setActiveTraceTab,
    ingestionSteps,
    uploadKBFile,
    isIngesting,
    isIngestionSidebarOpen,
    setIsIngestionSidebarOpen,
  };
}
