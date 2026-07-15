import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { resolveIdempotencyKey } from '../../lib/http/idempotency';
import { chatKeys } from '../../query/keys/chat';
import { getSessionDetailAPI } from '../../api/chat';
import { streamChatQuery } from '../../streams/chat-stream';
import { submitRepoReadmeCheckAPI } from '../../api/repo-analysis';
import type { ChatMessage } from '../../types/chat';
import type {
  SendMessageOptions,
  UseChatStreamParams,
  UseChatStreamReturn,
} from './use-chat-stream-types';

export type {
  ChatMode,
  SendMessageOptions,
  SessionStreamActions,
  TraceStreamActions,
  UseChatStreamParams,
  UseChatStreamReturn,
} from './use-chat-stream-types';

const RETRY_CACHE_TTL_MS = 5 * 60 * 1000;

type RetryCacheEntry = {
  clientRequestId: string;
  query: string;
  createdAt: number;
};

function tempMessage(
  partial: Pick<ChatMessage, 'id' | 'session_id' | 'role' | 'content' | 'status'> &
    Partial<ChatMessage>,
): ChatMessage {
  const now = new Date().toISOString();
  return { created_at: now, updated_at: now, ...partial };
}

export function useChatStream({
  userId,
  refreshUser,
  chatMode,
  activeSessionId,
  displayedMessages,
  sessionActions,
  traceActions,
  resolveDefaultKbId,
}: UseChatStreamParams): UseChatStreamReturn {
  const queryClient = useQueryClient();
  const [streamingText, setStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const retryCacheRef = useRef<Map<string, RetryCacheEntry>>(new Map());
  const latestRef = useRef({
    sessionActions,
    traceActions,
    chatMode,
    activeSessionId,
    userId,
    resolveDefaultKbId,
    refreshUser,
    displayedMessages,
  });
  useEffect(() => {
    latestRef.current = {
      sessionActions,
      traceActions,
      chatMode,
      activeSessionId,
      userId,
      resolveDefaultKbId,
      refreshUser,
      displayedMessages,
    };
  });

  const pruneRetryCache = useCallback(() => {
    const now = Date.now();
    for (const [messageId, entry] of retryCacheRef.current.entries()) {
      if (now - entry.createdAt > RETRY_CACHE_TTL_MS) {
        retryCacheRef.current.delete(messageId);
      }
    }
  }, []);

  const abort = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  const resetStream = useCallback(() => {
    abortControllerRef.current?.abort();
    retryCacheRef.current.clear();
    setStreamingText('');
    setIsStreaming(false);
  }, []);

  useEffect(() => () => {
    abortControllerRef.current?.abort();
  }, []);

  const sendQuery = useCallback(async (text: string, options?: SendMessageOptions) => {
    const normalizedText = text.trim();
    if (!normalizedText || latestRef.current.userId == null) return;

    const {
      sessionActions: session,
      traceActions: trace,
      chatMode: mode,
      activeSessionId: sessionId,
    } = latestRef.current;

    abortControllerRef.current?.abort();
    const newController = new AbortController();
    abortControllerRef.current = newController;
    pruneRetryCache();
    session.enterLiveMode();

    if (mode === 'repo_check') {
      if (options?.addUserMessage ?? true) {
        session.appendMessage(tempMessage({
          id: `temp-user-${Date.now()}`,
          session_id: sessionId || '',
          role: 'user',
          content: normalizedText,
          status: 'success',
        }));
      }
      setIsStreaming(false);
      setStreamingText('');
      try {
        const response = await submitRepoReadmeCheckAPI(normalizedText);
        if (newController.signal.aborted) return;
        session.appendMessage(tempMessage({
          id: `repo-check-msg-${Date.now()}`,
          session_id: sessionId || '',
          role: 'assistant',
          content: '',
          status: 'success',
          message_metadata: { type: 'repo_check_run', run_id: response.run_id },
        }));
      } catch (err: unknown) {
        if (newController.signal.aborted) return;
        const errorMessage =
          err instanceof Error
            ? err.message
            : '仓库分析任务创建失败，请确保输入了合法的 GitHub 仓库 URL。';
        session.appendMessage(tempMessage({
          id: `repo-check-err-${Date.now()}`,
          session_id: sessionId || '',
          role: 'assistant',
          content: errorMessage || '仓库分析任务创建失败，请确保输入了合法的 GitHub 仓库 URL。',
          status: 'failed',
        }));
      }
      return;
    }

    const addUserMessage = options?.addUserMessage ?? true;
    const clientRequestId = resolveIdempotencyKey(options?.clientRequestId);
    if (options?.retryMessageId) {
      retryCacheRef.current.delete(options.retryMessageId);
    }
    if (addUserMessage) {
      session.appendMessage(tempMessage({
        id: `temp-user-${Date.now()}`,
        session_id: sessionId || '',
        role: 'user',
        content: normalizedText,
        status: 'success',
      }));
    }
    setIsStreaming(true);
    setStreamingText('');
    trace.reset();

    const enableExternalContext = mode === 'web_rag';
    let targetKbId: string | undefined;
    if (!sessionId && (mode === 'rag' || mode === 'web_rag')) {
      const kbId = await latestRef.current.resolveDefaultKbId();
      if (newController.signal.aborted) return;
      if (kbId) {
        targetKbId = kbId;
      } else if (mode === 'rag') {
        setIsStreaming(false);
        const failedMessageId = `temp-err-${Date.now()}`;
        session.appendMessage(tempMessage({
          id: failedMessageId,
          session_id: '',
          role: 'assistant',
          content: '无法获取默认知识库，请确保系统已配置知识库后再试。',
          status: 'failed',
        }));
        retryCacheRef.current.set(failedMessageId, {
          clientRequestId,
          query: normalizedText,
          createdAt: Date.now(),
        });
        return;
      }
    }
    if (newController.signal.aborted) return;

    let runtimeSessionId: string | null = sessionId;
    let metaReceived = false;
    let messageId = '';
    let accumulatedContent = '';
    const queryStartTime = Date.now();

    streamChatQuery(
      {
        query: normalizedText,
        sessionId: sessionId || undefined,
        kbId: targetKbId,
        clientRequestId,
        enableExternalContext,
        signal: newController.signal,
      },
      {
        onStarted() {
          if (newController.signal.aborted) return;
          latestRef.current.traceActions.markNetworkStarted(Date.now() - queryStartTime);
        },
        onMeta(event) {
          if (newController.signal.aborted || metaReceived) return;
          metaReceived = true;
          messageId = event.message_id || '';
          runtimeSessionId = event.session_id || runtimeSessionId;
          const latest = latestRef.current;
          latest.traceActions.applyMetaSkips(latest.chatMode);
          if (!sessionId) {
            latest.sessionActions.commitSession({
              id: event.session_id,
              title: event.session_title,
              user_id: String(latest.userId ?? ''),
              kb_id: targetKbId || null,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              total_tokens: 0,
            });
            queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
          }
        },
        onStep(event) {
          if (newController.signal.aborted) return;
          latestRef.current.traceActions.handleStep(event);
        },
        onChunk(event) {
          if (newController.signal.aborted) return;
          accumulatedContent += event.content;
          setStreamingText((prev) => prev + event.content);
        },
        onDone() {
          if (newController.signal.aborted) return;
          const latest = latestRef.current;
          latest.sessionActions.appendMessage(tempMessage({
            id: messageId || `msg-${Date.now()}`,
            session_id: runtimeSessionId || '',
            role: 'assistant',
            content: accumulatedContent,
            status: 'success',
          }));
          setStreamingText('');
          setIsStreaming(false);
          latest.sessionActions.enterLiveMode();
          latest.traceActions.completeIdle();
          latest.refreshUser().catch(() => { });
          if (runtimeSessionId) {
            queryClient.invalidateQueries({
              queryKey: chatKeys.sessionDetail(runtimeSessionId),
            });
            getSessionDetailAPI(runtimeSessionId)
              .then((detail) => {
                if (newController.signal.aborted) return;
                const current = latestRef.current;
                current.sessionActions.commitSession(detail.session);
                current.sessionActions.updateMessages(() => detail.messages || []);
                const lastAssistantMsg = [...detail.messages]
                  .reverse()
                  .find((m) => m.role === 'assistant');
                current.traceActions.applyDetailFromAssistant(
                  lastAssistantMsg,
                  detail.session,
                );
              })
              .catch(() => { });
          }
          queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
        },
        onError(err) {
          if (newController.signal.aborted) return;
          setIsStreaming(false);
          setStreamingText('');
          const latest = latestRef.current;
          latest.traceActions.markError();
          const failedMessageId = `temp-err-${Date.now()}`;
          latest.sessionActions.appendMessage(tempMessage({
            id: failedMessageId,
            session_id: latest.activeSessionId || '',
            role: 'assistant',
            content: err.message || '请求处理失败，请稍后重试',
            status: 'failed',
          }));
          retryCacheRef.current.set(failedMessageId, {
            clientRequestId,
            query: normalizedText,
            createdAt: Date.now(),
          });
        },
      },
    );
  }, [pruneRetryCache, queryClient]);

  const retryFailedMessage = useCallback((messageId: string) => {
    if (isStreaming) return;
    pruneRetryCache();

    let queryText = '';
    let clientRequestId: string | undefined;
    const entry = retryCacheRef.current.get(messageId);
    if (entry) {
      queryText = entry.query;
      clientRequestId = entry.clientRequestId;
    } else {
      const messages = latestRef.current.displayedMessages;
      const msgIndex = messages.findIndex((msg) => msg.id === messageId);
      if (msgIndex > 0) {
        const prevMsg = messages[msgIndex - 1];
        if (prevMsg?.role === 'user') queryText = prevMsg.content;
      }
    }
    if (!queryText) return;
    if (entry) retryCacheRef.current.delete(messageId);

    // Live messages are hydrated from history detail (PR5); delete from live state only.
    latestRef.current.sessionActions.updateMessages((prev) =>
      prev.filter((msg) => msg.id !== messageId),
    );
    void sendQuery(queryText, {
      clientRequestId,
      addUserMessage: false,
      retryMessageId: messageId,
    });
  }, [isStreaming, pruneRetryCache, sendQuery]);

  return {
    streamingText,
    isStreaming,
    sendQuery,
    retryFailedMessage,
    abort,
    resetStream,
  };
}
