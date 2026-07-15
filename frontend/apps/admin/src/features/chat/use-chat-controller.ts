import { useState, useCallback, useRef, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../context/useAuth';
import { resolveIdempotencyKey } from '../../lib/http/idempotency';
import { chatKeys } from '../../query/keys/chat';
import { getSessionDetailAPI } from '../../api/chat';
import { streamChatQuery } from '../../streams/chat-stream';
import { defaultKBQueryOptions, useDefaultKBQuery } from '../../query/hooks/knowledge';
import { submitRepoReadmeCheckAPI } from '../../api/repo-analysis';
import { useKbIngestion } from '../knowledge/use-kb-ingestion';
import { useChatSessionState } from './use-chat-session-state';
import type { ChatMessage, ChatSession } from '../../types/chat';
import type { ChatStreamStepEvent } from '../../schemas/chat';
import {
    applyTraceMetricsToSteps,
    createInitialTraceSteps,
    parseCitations,
    parseChatMessageMetrics,
    parseRagMetrics,
    TRACE_STEP_DEFS,
} from '../../types/agent-trace';
import type {
    AgentTraceStep,
    CitationItem,
} from '../../types/agent-trace';

const RETRY_CACHE_TTL_MS = 5 * 60 * 1000;

type RetryCacheEntry = {
    clientRequestId: string;
    query: string;
    createdAt: number;
};

type SendMessageOptions = {
    clientRequestId?: string;
    addUserMessage?: boolean;
    retryMessageId?: string;
};

export type ChatMode = 'normal' | 'rag' | 'web_rag' | 'repo_check';

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

    const [streamingText, setStreamingText] = useState('');
    const [isStreaming, setIsStreaming] = useState(false);
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

    // enabled:false — no auto fetch; first RAG send resolves via fetchQuery (TQ v5
    // no-ops observer refetch while disabled). Same options as useDefaultKBQuery.
    const { data: defaultKb } = useDefaultKBQuery({ enabled: false });

    // Manual memoization kept for stable identity across sendQuery; compiler cannot prove deps.
    // eslint-disable-next-line react-hooks/preserve-manual-memoization -- fetchQuery closure over user/defaultKb
    const fetchDefaultKbId = useCallback(async (): Promise<string | null> => {
        // Imperative fetchQuery bypasses observer enabled — require confirmed identity first.
        if (!user?.id) return null;
        if (defaultKb?.id) return defaultKb.id;
        try {
            const kb = await queryClient.fetchQuery(defaultKBQueryOptions());
            return kb.id;
        } catch (err) {
            console.error('获取默认知识库失败:', err);
            return null;
        }
    }, [defaultKb?.id, queryClient, user?.id]);

    const abortControllerRef = useRef<AbortController | null>(null);
    const retryCacheRef = useRef<Map<string, RetryCacheEntry>>(new Map());
    /** Last confirmed bootstrap user id; null means anonymous. */
    const lastConfirmedUserIdRef = useRef<string | null>(null);
    /** Bumped on identity teardown; deferred promises must re-check before setState. */
    const identityGenerationRef = useRef(0);

    const isCurrentIdentity = useCallback((generation: number) => {
        return generation === identityGenerationRef.current;
    }, []);

    /** Shared session-level reset used by startNewChat and identity teardown. */
    const resetChatSessionState = useCallback(() => {
        abortControllerRef.current?.abort();
        retryCacheRef.current.clear();
        resetSession();
        setChatMode('normal');
        setStreamingText('');
        setIsStreaming(false);
        setTraceSteps([]);
        setCitations([]);
    }, [resetSession]);

    /** Full identity teardown: session + ingestion runtime. */
    const resetIdentityRuntime = useCallback(() => {
        identityGenerationRef.current += 1;
        resetChatSessionState();
        resetIngestion();
    }, [resetChatSessionState, resetIngestion]);

    useEffect(() => {
        return () => {
            identityGenerationRef.current += 1;
            abortControllerRef.current?.abort();
            // useKbIngestion owns its unmount cleanup; stream abort stays here.
        };
    }, []);

    // Identity transitions:
    // - A→null or A→B: full runtime reset (also bumps generation)
    // - null→B: bump generation + abort so deferred anonymous work cannot land on B
    //   without wiping a fresh empty session UI
    useEffect(() => {
        const nextUserId = user?.id != null ? String(user.id) : null;
        const previousUserId = lastConfirmedUserIdRef.current;
        if (previousUserId !== null && previousUserId !== nextUserId) {
            // Identity teardown must reset session + ingestion runtime synchronously.
            // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional identity boundary
            resetIdentityRuntime();
        } else if (previousUserId === null && nextUserId !== null) {
            identityGenerationRef.current += 1;
            abortControllerRef.current?.abort();
            // Invalidate in-flight ingestion without wiping a fresh empty session UI.
            resetIngestion();
        }
        lastConfirmedUserIdRef.current = nextUserId;
    }, [user?.id, resetIdentityRuntime, resetIngestion]);

    // History detail arrived: controller owns mode / trace / citation only.
    // Message hydration lives in useChatSessionState.
    useEffect(() => {
        if (!isSessionFromHistory || !sessionDetailData) return;
        const lastAssistantMsg = [...(sessionDetailData.messages || [])]
            .reverse()
            .find((m) => m.role === 'assistant');
        const lastMetrics = parseRagMetrics(lastAssistantMsg?.search_context);
        if (sessionDetailData.session) {
            if (lastMetrics?.external_context_used) {
                // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate mode/trace from detail
                setChatMode('web_rag');
            } else if (sessionDetailData.session.kb_id) {
                setChatMode('rag');
            } else {
                setChatMode('normal');
            }
        }
        if (lastAssistantMsg?.search_context) {
            setCitations(parseCitations(lastAssistantMsg.search_context));
        } else {
            setCitations([]);
        }
        setTraceSteps((prev) => applyTraceMetricsToSteps(
            prev,
            parseChatMessageMetrics(lastAssistantMsg?.message_metadata),
            parseRagMetrics(lastAssistantMsg?.search_context),
        ));
    }, [isSessionFromHistory, sessionDetailData]);

    const pruneRetryCache = useCallback(() => {
        const now = Date.now();
        for (const [messageId, entry] of retryCacheRef.current.entries()) {
            if (now - entry.createdAt > RETRY_CACHE_TTL_MS) {
                retryCacheRef.current.delete(messageId);
            }
        }
    }, []);

    const advanceToStep = useCallback((targetStepId: string) => {
        const targetIdx = TRACE_STEP_DEFS.findIndex((d) => d.id === targetStepId);
        if (targetIdx === -1) {
            if (import.meta.env.DEV) {
                console.warn(`[advanceToStep] Unknown step id: "${targetStepId}"`);
            }
            return;
        }

        setTraceSteps((prev) => {
            const now = Date.now();
            return prev.map((step, idx) => {
                if (
                    idx < targetIdx &&
                    step.status !== 'done' &&
                    step.status !== 'error' &&
                    step.status !== 'skipped'
                ) {
                    return { ...step, status: 'done' as const, finishedAt: now };
                }
                if (
                    idx === targetIdx &&
                    step.status !== 'done' &&
                    step.status !== 'error'
                ) {
                    return {
                        ...step,
                        status: 'running' as const,
                        startedAt: step.startedAt ?? now,
                    };
                }
                return step;
            });
        });
    }, []);

    const handleStreamStep = useCallback((event: ChatStreamStepEvent) => {
        const now = Date.now();
        const targetIdx = TRACE_STEP_DEFS.findIndex((def) => def.id === event.step);
        if (targetIdx === -1) return;

        setTraceSteps((prev) =>
            prev.map((step, idx) => {
                if (step.id === event.step) {
                    if (event.status === 'running') {
                        return {
                            ...step,
                            status: 'running' as const,
                            startedAt: step.startedAt ?? now,
                        };
                    }
                    if (event.status === 'skipped') {
                        return {
                            ...step,
                            status: 'skipped' as const,
                            finishedAt: now,
                        };
                    }
                    const durationMs =
                        step.startedAt !== null ? now - step.startedAt : step.durationMs;
                    return {
                        ...step,
                        status: 'done' as const,
                        finishedAt: now,
                        durationMs,
                        metricDetails: event.metrics,
                    };
                }
                if (
                    event.status === 'running' &&
                    idx < targetIdx &&
                    step.status !== 'done' &&
                    step.status !== 'error' &&
                    step.status !== 'skipped'
                ) {
                    return { ...step, status: 'done' as const, finishedAt: now };
                }
                return step;
            }),
        );

        if (event.status === 'running') {
            advanceToStep(event.step);
        }
    }, [advanceToStep]);

    const sendQuery = useCallback(async (text: string, options?: SendMessageOptions) => {
        const normalizedText = text.trim();
        if (!normalizedText) return;
        // Require bootstrap-confirmed user — never fire identity-bound APIs anonymously.
        if (user?.id == null) return;

        const generation = identityGenerationRef.current;

        // Abort any in-flight stream before starting a new one
        abortControllerRef.current?.abort();

        const newController = new AbortController();
        abortControllerRef.current = newController;

        pruneRetryCache();
        enterLiveMode();

        if (chatMode === 'repo_check') {
            const addUserMessage = options?.addUserMessage ?? true;
            if (addUserMessage) {
                const userMsg: ChatMessage = {
                    id: `temp-user-${Date.now()}`,
                    session_id: activeSessionId || '',
                    role: 'user',
                    content: normalizedText,
                    status: 'success',
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                };
                appendMessage(userMsg);
            }
            setIsStreaming(false);
            setStreamingText('');

            try {
                const response = await submitRepoReadmeCheckAPI(normalizedText);
                if (!isCurrentIdentity(generation) || newController.signal.aborted) return;
                const assistantMsg: ChatMessage = {
                    id: `repo-check-msg-${Date.now()}`,
                    session_id: activeSessionId || '',
                    role: 'assistant',
                    content: '',
                    status: 'success',
                    message_metadata: {
                        type: 'repo_check_run',
                        run_id: response.run_id,
                    },
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                };
                appendMessage(assistantMsg);
            } catch (err: unknown) {
                if (!isCurrentIdentity(generation) || newController.signal.aborted) return;
                const errorMessage =
                    err instanceof Error
                        ? err.message
                        : '仓库分析任务创建失败，请确保输入了合法的 GitHub 仓库 URL。';
                const assistantMsg: ChatMessage = {
                    id: `repo-check-err-${Date.now()}`,
                    session_id: activeSessionId || '',
                    role: 'assistant',
                    content: errorMessage || '仓库分析任务创建失败，请确保输入了合法的 GitHub 仓库 URL。',
                    status: 'failed',
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                };
                appendMessage(assistantMsg);
            }
            return;
        }

        const addUserMessage = options?.addUserMessage ?? true;
        const clientRequestId = resolveIdempotencyKey(options?.clientRequestId);

        if (options?.retryMessageId) {
            retryCacheRef.current.delete(options.retryMessageId);
        }

        if (addUserMessage) {
            const userMsg: ChatMessage = {
                id: `temp-user-${Date.now()}`,
                session_id: activeSessionId || '',
                role: 'user',
                content: normalizedText,
                status: 'success',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            };
            appendMessage(userMsg);
        }
        setIsStreaming(true);
        setStreamingText('');
        setTraceSteps(createInitialTraceSteps());
        setCitations([]);

        const enableExternalContext = chatMode === 'web_rag';
        let targetKbId: string | undefined = undefined;
        if (!activeSessionId && (chatMode === 'rag' || chatMode === 'web_rag')) {
            const kbId = await fetchDefaultKbId();
            if (!isCurrentIdentity(generation) || newController.signal.aborted) return;
            if (kbId) {
                targetKbId = kbId;
            } else if (chatMode === 'rag') {
                setIsStreaming(false);
                const failedMessageId = `temp-err-${Date.now()}`;
                const errorMsg: ChatMessage = {
                    id: failedMessageId,
                    session_id: '',
                    role: 'assistant',
                    content: '无法获取默认知识库，请确保系统已配置知识库后再试。',
                    status: 'failed',
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                };
                appendMessage(errorMsg);
                retryCacheRef.current.set(failedMessageId, {
                    clientRequestId,
                    query: normalizedText,
                    createdAt: Date.now(),
                });
                return;
            }
        }

        if (!isCurrentIdentity(generation) || newController.signal.aborted) return;

        let runtimeSessionId: string | null = activeSessionId;
        let metaReceived = false;
        let messageId = '';
        let accumulatedContent = '';

        const queryStartTime = Date.now();

        streamChatQuery(
            {
                query: normalizedText,
                sessionId: activeSessionId || undefined,
                kbId: targetKbId,
                clientRequestId,
                enableExternalContext,
                signal: newController.signal,
            },
            {
                onStarted() {
                    if (!isCurrentIdentity(generation) || newController.signal.aborted) return;
                    const networkMs = Date.now() - queryStartTime;
                    setTraceSteps((prev) =>
                        prev.map((step) =>
                            step.id === 'receive-query'
                                ? {
                                    ...step,
                                    status: 'done' as const,
                                    finishedAt: Date.now(),
                                    durationMs: networkMs,
                                    description: '网络连接建立成功',
                                }
                                : step
                        )
                    );
                },
                onMeta(event) {
                    if (!isCurrentIdentity(generation) || newController.signal.aborted) return;
                    if (metaReceived) return;
                    metaReceived = true;
                    messageId = event.message_id || '';
                    runtimeSessionId = event.session_id || runtimeSessionId;

                    const currentMode = chatMode;
                    const now = Date.now();

                    setTraceSteps((prev) => {
                        return prev.map((step) => {
                            if (step.id === 'receive-query') {
                                return { ...step, status: 'done' as const, finishedAt: now };
                            }
                            if (step.id === 'kb-search') {
                                if (currentMode === 'normal') {
                                    return { ...step, status: 'skipped' as const, finishedAt: now };
                                }
                                return step;
                            }
                            if (step.id === 'local-search') {
                                return { ...step, status: 'skipped' as const, finishedAt: now };
                            }
                            if (step.id === 'web-search') {
                                if (currentMode === 'normal' || currentMode === 'rag') {
                                    return { ...step, status: 'skipped' as const, finishedAt: now };
                                }
                                return step;
                            }
                            return step;
                        });
                    });

                    if (!activeSessionId) {
                        commitSession({
                            id: event.session_id,
                            title: event.session_title,
                            user_id: String(user?.id ?? ''),
                            kb_id: targetKbId || null,
                            created_at: new Date().toISOString(),
                            updated_at: new Date().toISOString(),
                            total_tokens: 0,
                        });
                        queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
                    }
                },
                onStep(event) {
                    if (!isCurrentIdentity(generation) || newController.signal.aborted) return;
                    handleStreamStep(event);
                },
                onChunk(event) {
                    if (!isCurrentIdentity(generation) || newController.signal.aborted) return;
                    accumulatedContent += event.content;
                    setStreamingText((prev) => prev + event.content);
                },
                onDone() {
                    if (!isCurrentIdentity(generation) || newController.signal.aborted) return;
                    const assistantMsg: ChatMessage = {
                        id: messageId || `msg-${Date.now()}`,
                        session_id: runtimeSessionId || '',
                        role: 'assistant',
                        content: accumulatedContent,
                        status: 'success',
                        created_at: new Date().toISOString(),
                        updated_at: new Date().toISOString(),
                    };
                    appendMessage(assistantMsg);
                    setStreamingText('');
                    setIsStreaming(false);
                    enterLiveMode();
                    setTraceSteps((prev) => {
                        const now = Date.now();
                        return prev.map((step) => {
                            if (
                                step.status !== 'done' &&
                                step.status !== 'error' &&
                                step.status !== 'skipped'
                            ) {
                                return {
                                    ...step,
                                    status: 'done' as const,
                                    finishedAt: now,
                                };
                            }
                            return step;
                        });
                    });
                    refreshUser().catch(() => { });
                    if (runtimeSessionId) {
                        queryClient.invalidateQueries({ queryKey: chatKeys.sessionDetail(runtimeSessionId) });
                        getSessionDetailAPI(runtimeSessionId)
                            .then((detail) => {
                                if (!isCurrentIdentity(generation) || newController.signal.aborted) {
                                    return;
                                }
                                commitSession(detail.session);
                                updateMessages(() => detail.messages || []);
                                const lastAssistantMsg = [
                                    ...detail.messages,
                                ]
                                    .reverse()
                                    .find((m) => m.role === 'assistant');
                                const lastMetrics = parseRagMetrics(lastAssistantMsg?.search_context);
                                if (lastMetrics?.external_context_used && detail.session?.kb_id) {
                                    setChatMode('web_rag');
                                }
                                if (lastAssistantMsg?.search_context) {
                                    setCitations(
                                        parseCitations(
                                            lastAssistantMsg.search_context,
                                        ),
                                    );
                                } else {
                                    setCitations([]);
                                }
                                setTraceSteps((prev) => applyTraceMetricsToSteps(
                                    prev,
                                    parseChatMessageMetrics(lastAssistantMsg?.message_metadata),
                                    parseRagMetrics(lastAssistantMsg?.search_context),
                                ));
                            })
                            .catch(() => { });
                    }
                    queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
                },
                onError(err) {
                    if (!isCurrentIdentity(generation) || newController.signal.aborted) return;
                    setIsStreaming(false);
                    setStreamingText('');
                    setTraceSteps((prev) => {
                        const now = Date.now();
                        const runningIdx = prev.findIndex(
                            (s) => s.status === 'running',
                        );
                        return prev.map((step, idx) => {
                            if (idx === runningIdx)
                                return {
                                    ...step,
                                    status: 'error' as const,
                                    finishedAt: now,
                                };
                            if (idx > runningIdx && step.status === 'idle')
                                return { ...step, status: 'skipped' as const };
                            return step;
                        });
                    });
                    const errorMessage = err.message || '请求处理失败，请稍后重试';
                    const failedMessageId = `temp-err-${Date.now()}`;
                    const errorMsg: ChatMessage = {
                        id: failedMessageId,
                        session_id: activeSessionId || '',
                        role: 'assistant',
                        content: errorMessage,
                        status: 'failed',
                        created_at: new Date().toISOString(),
                        updated_at: new Date().toISOString(),
                    };
                    appendMessage(errorMsg);
                    retryCacheRef.current.set(failedMessageId, {
                        clientRequestId,
                        query: normalizedText,
                        createdAt: Date.now(),
                    });
                },
            },
        );
    }, [
        activeSessionId,
        appendMessage,
        chatMode,
        commitSession,
        enterLiveMode,
        fetchDefaultKbId,
        handleStreamStep,
        isCurrentIdentity,
        pruneRetryCache,
        queryClient,
        refreshUser,
        updateMessages,
        user?.id,
    ]);

    const retryFailedMessage = useCallback((messageId: string) => {
        if (import.meta.env.DEV) console.log('[retry] 点击重试, messageId=', messageId, 'isStreaming=', isStreaming);
        if (import.meta.env.DEV) console.log('[retry] 当前缓存 keys=', [...retryCacheRef.current.keys()]);
        if (isStreaming) {
            if (import.meta.env.DEV) console.log('[retry] 放弃：正在流式中');
            return;
        }
        pruneRetryCache();

        let queryText = '';
        let clientRequestId: string | undefined = undefined;

        const entry = retryCacheRef.current.get(messageId);
        if (entry) {
            queryText = entry.query;
            clientRequestId = entry.clientRequestId;
            if (import.meta.env.DEV) console.log('[retry] 命中缓存，queryText=', queryText);
        } else {
            if (import.meta.env.DEV) console.log('[retry] 缓存未命中，尝试从消息历史查找');
            const msgIndex = displayedMessages.findIndex((msg) => msg.id === messageId);
            if (msgIndex > 0) {
                const prevMsg = displayedMessages[msgIndex - 1];
                if (prevMsg && prevMsg.role === 'user') {
                    queryText = prevMsg.content;
                    if (import.meta.env.DEV) console.log('[retry] 从消息历史中找到前一条用户提问作为重试内容:', queryText);
                }
            }
        }

        if (!queryText) {
            if (import.meta.env.DEV) console.log('[retry] 放弃：缓存里找不到该 messageId，且在消息列表中找不到对应的用户提问');
            return;
        }

        if (entry) {
            retryCacheRef.current.delete(messageId);
        }

        updateMessages((prev) => {
            const baseMessages = isSessionFromHistory && sessionDetailData
                ? sessionDetailData.messages || []
                : prev;
            return baseMessages.filter((msg) => msg.id !== messageId);
        });

        void sendQuery(queryText, {
            clientRequestId,
            addUserMessage: false,
            retryMessageId: messageId,
        });
    }, [
        displayedMessages,
        isSessionFromHistory,
        isStreaming,
        pruneRetryCache,
        sendQuery,
        sessionDetailData,
        updateMessages,
    ]);

    const selectSession = useCallback((session: ChatSession) => {
        // Same history session re-selected: skip reset so hydration effects do not need
        // to re-run (session id / history flag / detail data are unchanged).
        if (isSessionFromHistory && activeSessionId === session.id) {
            return;
        }
        selectSessionState(session);
        setChatMode(session.kb_id ? 'rag' : 'normal');
        retryCacheRef.current.clear();
        setTraceSteps([]);
        setCitations([]);
    }, [activeSessionId, isSessionFromHistory, selectSessionState]);

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
