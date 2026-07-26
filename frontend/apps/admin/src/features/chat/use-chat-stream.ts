import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { resolveIdempotencyKey } from '../../lib/http/idempotency';
import { chatKeys } from '../../query/keys/chat';
import {
  getGenerationRequestAPI,
  getSessionDetailAPI,
  resolveGenerationRequestAPI,
} from '../../api/chat';
import {
  ChatStreamError,
  streamChatQuery,
  streamChatRetry,
} from '../../streams/chat-stream';
import { submitRepoReadmeCheckAPI } from '../../api/repo-analysis';
import type { ChatMessage } from '../../types/chat';
import type { GenerationRequestStatus } from '../../schemas/chat';
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

function tempMessage(
  partial: Pick<ChatMessage, 'id' | 'session_id' | 'role' | 'content' | 'status'> &
    Partial<ChatMessage>,
): ChatMessage {
  const now = new Date().toISOString();
  return { created_at: now, updated_at: now, ...partial };
}

async function resolveGenerationStatus(
  generationRequestId: string | undefined,
  clientRequestId: string | undefined,
): Promise<GenerationRequestStatus | null> {
  try {
    if (generationRequestId) {
      return await getGenerationRequestAPI(generationRequestId);
    }
    if (clientRequestId) {
      return await resolveGenerationRequestAPI(clientRequestId);
    }
  } catch {
    // Missing or unauthorized identity is intentionally non-retryable.
  }
  return null;
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
  explicitRetryEnabled,
}: UseChatStreamParams): UseChatStreamReturn {
  const queryClient = useQueryClient();
  const [streamingText, setStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const latestRef = useRef({
    sessionActions,
    traceActions,
    chatMode,
    activeSessionId,
    userId,
    resolveDefaultKbId,
    refreshUser,
    displayedMessages,
    explicitRetryEnabled,
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
      explicitRetryEnabled,
    };
  });

  const abort = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  const resetStream = useCallback(() => {
    abortControllerRef.current?.abort();
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
          retryable: false,
          error_code: 'CHAT_PREFLIGHT_FAILED',
        }));
        return;
      }
    }
    if (newController.signal.aborted) return;

    let runtimeSessionId: string | null = sessionId;
    let metaReceived = false;
    let messageId = '';
    let generationRequestId: string | undefined;
    let generationAttempt: number | undefined;
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
          generationRequestId = event.generation_request_id;
          generationAttempt = event.attempt;
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
            generation_request_id: generationRequestId,
            attempt: generationAttempt,
            retryable: false,
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
          const streamError = err instanceof ChatStreamError ? err : null;
          const observedRequestId =
            streamError?.generationRequestId || generationRequestId;
          const observedAttempt = streamError?.attempt || generationAttempt;
          void resolveGenerationStatus(observedRequestId, clientRequestId).then(async (status) => {
            if (newController.signal.aborted) return;
            const current = latestRef.current;
            if (status?.status === 'succeeded') {
              current.traceActions.completeIdle();
              current.refreshUser().catch(() => { });
              queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
              queryClient.invalidateQueries({
                queryKey: chatKeys.sessionDetail(status.session_id),
              });
              try {
                const detail = await getSessionDetailAPI(status.session_id);
                if (newController.signal.aborted) return;
                const active = latestRef.current;
                active.sessionActions.commitSession(detail.session);
                active.sessionActions.updateMessages(() => detail.messages || []);
              } catch {
                if (newController.signal.aborted) return;
                current.sessionActions.appendMessage(tempMessage({
                  id: status.assistant_message_id || messageId || `temp-done-${Date.now()}`,
                  session_id: status.session_id,
                  role: 'assistant',
                  content: '请求已完成，请刷新页面查看结果。',
                  status: 'failed',
                  generation_request_id: status.generation_request_id,
                  attempt: status.attempt,
                  retryable: false,
                  error_code: 'CHAT_REQUEST_ALREADY_SUCCEEDED',
                }));
              }
              return;
            }

            current.traceActions.markError();
            const resolvedRequestId =
              status?.generation_request_id || observedRequestId;
            const resolvedAttempt = status?.attempt || observedAttempt;
            const isRunning = status != null && (
              status.status === 'prepared' ||
              status.status === 'queued' ||
              status.status === 'running'
            );
            const isRetryable = status?.status === 'failed' && status.retryable;
            current.sessionActions.appendMessage(tempMessage({
              id: status?.assistant_message_id || messageId || `temp-err-${Date.now()}`,
              session_id: status?.session_id || runtimeSessionId || '',
              role: 'assistant',
              content: isRunning
                ? '请求已被服务端接受，仍在生成中，请稍后刷新。'
                : status?.error_message || err.message || '请求处理失败，请稍后重试',
              status: 'failed',
              generation_request_id: resolvedRequestId,
              attempt: resolvedAttempt,
              retryable: isRetryable,
              error_code: isRunning
                ? 'CHAT_REQUEST_STILL_RUNNING'
                : status?.error_code || streamError?.errorCode || 'CHAT_REQUEST_IDENTITY_UNKNOWN',
            }));
            if (status?.session_id) {
              queryClient.invalidateQueries({
                queryKey: chatKeys.sessionDetail(status.session_id),
              });
            }
          });
        },
      },
    );
  }, [queryClient]);

  const retryFailedMessage = useCallback((messageId: string) => {
    const latest = latestRef.current;
    if (isStreaming || !latest.explicitRetryEnabled) return;
    const failedMessage = latest.displayedMessages.find(
      (message) => message.id === messageId,
    );
    if (
      !failedMessage?.retryable ||
      !failedMessage.generation_request_id ||
      failedMessage.attempt == null
    ) return;

    abortControllerRef.current?.abort();
    const retryController = new AbortController();
    abortControllerRef.current = retryController;
    let runtimeSessionId = failedMessage.session_id || latest.activeSessionId;
    let generationRequestId = failedMessage.generation_request_id;
    let generationAttempt = failedMessage.attempt;
    let accumulatedContent = '';
    const retryStartedAt = Date.now();

    latest.sessionActions.updateMessages((messages) =>
      messages.map((message) => message.id === messageId
        ? { ...message, content: '', status: 'thinking', retryable: false }
        : message),
    );
    latest.traceActions.reset();
    setStreamingText('');
    setIsStreaming(true);

    streamChatRetry(
      {
        generationRequestId,
        expectedAttempt: generationAttempt,
        sessionId: runtimeSessionId || undefined,
        signal: retryController.signal,
      },
      {
        onStarted() {
          if (retryController.signal.aborted) return;
          latestRef.current.traceActions.markNetworkStarted(
            Date.now() - retryStartedAt,
          );
        },
        onMeta(event) {
          if (retryController.signal.aborted) return;
          runtimeSessionId = event.session_id || runtimeSessionId;
          generationRequestId = event.generation_request_id || generationRequestId;
          generationAttempt = event.attempt || generationAttempt;
          latestRef.current.traceActions.applyMetaSkips(
            latestRef.current.chatMode,
          );
        },
        onStep(event) {
          if (retryController.signal.aborted) return;
          latestRef.current.traceActions.handleStep(event);
        },
        onChunk(event) {
          if (retryController.signal.aborted) return;
          accumulatedContent += event.content;
          setStreamingText((previous) => previous + event.content);
        },
        onDone() {
          if (retryController.signal.aborted) return;
          setStreamingText('');
          setIsStreaming(false);
          const current = latestRef.current;
          current.traceActions.completeIdle();
          current.refreshUser().catch(() => { });
          current.sessionActions.updateMessages((messages) =>
            messages.map((message) => message.id === messageId
              ? {
                ...message,
                content: accumulatedContent,
                status: 'success',
                generation_request_id: generationRequestId,
                attempt: generationAttempt,
                retryable: false,
                error_code: undefined,
              }
              : message),
          );
          if (runtimeSessionId) {
            queryClient.invalidateQueries({
              queryKey: chatKeys.sessionDetail(runtimeSessionId),
            });
            getSessionDetailAPI(runtimeSessionId).then((detail) => {
              if (retryController.signal.aborted) return;
              const active = latestRef.current;
              active.sessionActions.commitSession(detail.session);
              active.sessionActions.updateMessages(() => detail.messages || []);
            }).catch(() => { });
          }
          queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
        },
        onError(error) {
          if (retryController.signal.aborted) return;
          setStreamingText('');
          setIsStreaming(false);
          const streamError = error instanceof ChatStreamError ? error : null;
          const observedRequestId =
            streamError?.generationRequestId || generationRequestId;
          void resolveGenerationStatus(observedRequestId, undefined).then(async (status) => {
            if (retryController.signal.aborted) return;
            if (status?.status === 'succeeded') {
              latestRef.current.traceActions.completeIdle();
              queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
              queryClient.invalidateQueries({
                queryKey: chatKeys.sessionDetail(status.session_id),
              });
              try {
                const detail = await getSessionDetailAPI(status.session_id);
                if (retryController.signal.aborted) return;
                const active = latestRef.current;
                active.sessionActions.commitSession(detail.session);
                active.sessionActions.updateMessages(() => detail.messages || []);
              } catch {
                if (retryController.signal.aborted) return;
                latestRef.current.sessionActions.updateMessages((messages) =>
                  messages.map((message) => message.id === messageId
                    ? {
                      ...message,
                      content: '请求已完成，请刷新页面查看结果。',
                      status: 'failed',
                      generation_request_id: status.generation_request_id,
                      attempt: status.attempt,
                      retryable: false,
                      error_code: 'CHAT_REQUEST_ALREADY_SUCCEEDED',
                    }
                    : message),
                );
              }
              return;
            }

            latestRef.current.traceActions.markError();
            const isRunning = status != null && (
              status.status === 'prepared' ||
              status.status === 'queued' ||
              status.status === 'running'
            );
            const canRetry = streamError?.retryable === false
              ? false
              : status?.status === 'failed' && status.retryable;
            latestRef.current.sessionActions.updateMessages((messages) =>
              messages.map((message) => message.id === messageId
                ? {
                  ...message,
                  content: isRunning
                    ? '请求已被服务端接受，仍在生成中，请稍后刷新。'
                    : status?.error_message || error.message,
                  status: 'failed',
                  generation_request_id:
                    status?.generation_request_id || observedRequestId,
                  attempt: status?.attempt || streamError?.attempt || generationAttempt,
                  retryable: canRetry,
                  error_code: isRunning
                    ? 'CHAT_REQUEST_STILL_RUNNING'
                    : status?.error_code || streamError?.errorCode || 'CHAT_REQUEST_IDENTITY_UNKNOWN',
                }
                : message),
            );
          });
        },
      },
    );
  }, [isStreaming, queryClient]);

  return {
    streamingText,
    isStreaming,
    sendQuery,
    retryFailedMessage,
    abort,
    resetStream,
  };
}
