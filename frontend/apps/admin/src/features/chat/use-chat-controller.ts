import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { message } from 'antd';
import { useAuth } from '../../context/useAuth';
import { resolveIdempotencyKey } from '../../lib/http/idempotency';
import { chatKeys } from '../../query/keys/chat';
import { useSessionDetailQuery } from '../../query/hooks/chat';
import { getSessionDetailAPI } from '../../api/chat';
import { streamChatQuery } from '../../streams/chat-stream';
import { uploadKBFileAPI, getKBTaskStatusAPI } from '../../api/knowledge';
import { defaultKBQueryOptions, useDefaultKBQuery } from '../../query/hooks/knowledge';
import { submitRepoReadmeCheckAPI } from '../../api/repo-analysis';
import type { ChatMessage, ChatSession } from '../../types/chat';
import type { ChatStreamStepEvent } from '../../schemas/chat';
import {
    applyTraceMetricsToSteps,
    createInitialTraceSteps,
    createInitialIngestionSteps,
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

    const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
    const [activeSession, setActiveSession] = useState<ChatSession | null>(null);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [streamingText, setStreamingText] = useState('');
    const [isStreaming, setIsStreaming] = useState(false);
    const [isSessionFromHistory, setIsSessionFromHistory] = useState(false);
    const [traceSteps, setTraceSteps] = useState<AgentTraceStep[]>([]);
    const [citations, setCitations] = useState<CitationItem[]>([]);
    const [chatMode, setChatMode] = useState<ChatMode>('normal');
    const [activeTraceTab, setActiveTraceTab] = useState<'rag' | 'ingestion'>('rag');
    const [ingestionSteps, setIngestionSteps] = useState<AgentTraceStep[]>(createInitialIngestionSteps());
    const [isIngesting, setIsIngesting] = useState(false);
    const [isIngestionSidebarOpen, setIsIngestionSidebarOpen] = useState(false);

    // enabled:false — no auto fetch; first RAG send resolves via fetchQuery (TQ v5
    // no-ops observer refetch while disabled). Same options as useDefaultKBQuery.
    const { data: defaultKb } = useDefaultKBQuery({ enabled: false });

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
    const pollIntervalRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const tabSwitchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    /** Last confirmed bootstrap user id; null means anonymous. */
    const lastConfirmedUserIdRef = useRef<string | null>(null);
    /** Bumped on identity teardown; deferred promises must re-check before setState. */
    const identityGenerationRef = useRef(0);

    const isCurrentIdentity = useCallback((generation: number) => {
        return generation === identityGenerationRef.current;
    }, []);

    const clearIngestionTimers = useCallback(() => {
        if (pollIntervalRef.current) {
            clearTimeout(pollIntervalRef.current);
            pollIntervalRef.current = null;
        }
        if (tabSwitchTimerRef.current) {
            clearTimeout(tabSwitchTimerRef.current);
            tabSwitchTimerRef.current = null;
        }
    }, []);

    /** Shared session-level reset used by startNewChat and identity teardown. */
    const resetChatSessionState = useCallback(() => {
        abortControllerRef.current?.abort();
        retryCacheRef.current.clear();
        setIsSessionFromHistory(false);
        setActiveSessionId(null);
        setActiveSession(null);
        setChatMode('normal');
        setMessages([]);
        setStreamingText('');
        setIsStreaming(false);
        setTraceSteps([]);
        setCitations([]);
    }, []);

    /** Full identity teardown: session + KB cache + ingestion runtime. */
    const resetIdentityRuntime = useCallback(() => {
        identityGenerationRef.current += 1;
        resetChatSessionState();
        clearIngestionTimers();
        setIngestionSteps(createInitialIngestionSteps());
        setActiveTraceTab('rag');
        setIsIngestionSidebarOpen(false);
        setIsIngesting(false);
    }, [resetChatSessionState, clearIngestionTimers]);

    useEffect(() => {
        return () => {
            // Invalidate deferred upload/poll continuations after unmount (PR4-adjacent).
            identityGenerationRef.current += 1;
            abortControllerRef.current?.abort();
            if (pollIntervalRef.current) clearTimeout(pollIntervalRef.current);
            if (tabSwitchTimerRef.current) clearTimeout(tabSwitchTimerRef.current);
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
            resetIdentityRuntime();
        } else if (previousUserId === null && nextUserId !== null) {
            identityGenerationRef.current += 1;
            abortControllerRef.current?.abort();
            clearIngestionTimers();
        }
        lastConfirmedUserIdRef.current = nextUserId;
    }, [user?.id, resetIdentityRuntime, clearIngestionTimers]);

    const detailSessionId = isSessionFromHistory ? activeSessionId : null;
    const { data: sessionDetailData, isLoading: detailLoading } =
        useSessionDetailQuery(detailSessionId);

    const isLoadingHistory = detailLoading && isSessionFromHistory;

    const displayedActiveSession = isSessionFromHistory && sessionDetailData
        ? sessionDetailData.session
        : activeSession;
    const displayedMessages = useMemo(() => isSessionFromHistory && sessionDetailData
        ? sessionDetailData.messages || []
        : messages, [isSessionFromHistory, sessionDetailData, messages]);

    useEffect(() => {
        if (!isSessionFromHistory || !sessionDetailData) return;
        // Historical session selection hydrates local chat state from query data.
        setMessages(sessionDetailData.messages || []);
        const lastAssistantMsg = [...(sessionDetailData.messages || [])]
            .reverse()
            .find((m) => m.role === 'assistant');
        const lastMetrics = parseRagMetrics(lastAssistantMsg?.search_context);
        if (sessionDetailData.session) {
            if (lastMetrics?.external_context_used) {
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
        setIsSessionFromHistory(false);

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
                setMessages((prev) => [...prev, userMsg]);
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
                setMessages((prev) => [...prev, assistantMsg]);
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
                setMessages((prev) => [...prev, assistantMsg]);
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
            setMessages((prev) => [...prev, userMsg]);
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
                setMessages((prev) => [...prev, errorMsg]);
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
                        setActiveSessionId(event.session_id);
                        setActiveSession({
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
                    setMessages((prev) => [...prev, assistantMsg]);
                    setStreamingText('');
                    setIsStreaming(false);
                    setIsSessionFromHistory(false);
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
                                setActiveSession(detail.session);
                                setMessages(detail.messages || []);
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
                    setMessages((prev) => [...prev, errorMsg]);
                    retryCacheRef.current.set(failedMessageId, {
                        clientRequestId,
                        query: normalizedText,
                        createdAt: Date.now(),
                    });
                },
            },
        );
    }, [activeSessionId, pruneRetryCache, refreshUser, user?.id, queryClient, chatMode, fetchDefaultKbId, handleStreamStep, isCurrentIdentity]);

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

        setMessages((prev) => {
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
    }, [sendQuery, isStreaming, pruneRetryCache, displayedMessages, isSessionFromHistory, sessionDetailData]);

    const selectSession = useCallback((session: ChatSession) => {
        setIsSessionFromHistory(true);
        setActiveSessionId(session.id);
        setActiveSession(session);
        setChatMode(session.kb_id ? 'rag' : 'normal');
        retryCacheRef.current.clear();
        setMessages([]);
        setTraceSteps([]);
        setCitations([]);
    }, []);

    const startNewChat = useCallback(() => {
        resetChatSessionState();
    }, [resetChatSessionState]);



    const uploadKBFile = useCallback(async (file: File) => {
        if (user?.id == null) return;

        const suffix = file.name.split('.').pop()?.toLowerCase();
        if (suffix !== 'md' && suffix !== 'markdown') {
            message.error('仅支持上传 .md 或 .markdown 格式的文件！');
            return;
        }
        if (file.size > 20 * 1024 * 1024) {
            message.error('文件大小不能超过 20MB！');
            return;
        }

        const generation = identityGenerationRef.current;
        clearIngestionTimers();

        setIsIngesting(true);
        setActiveTraceTab('ingestion');
        setIsIngestionSidebarOpen(true);

        const now = Date.now();
        setIngestionSteps([
            { id: 'file-upload', status: 'running', description: `正在上传: ${file.name}`, startedAt: now, finishedAt: null },
            { id: 'content-audit', status: 'idle', description: '等待文件解析提取', startedAt: null, finishedAt: null },
            { id: 'semantic-chunk', status: 'idle', description: '等待分块处理', startedAt: null, finishedAt: null },
            { id: 'vector-index', status: 'idle', description: '等待构建向量索引', startedAt: null, finishedAt: null },
            { id: 'ingestion-complete', status: 'idle', description: '等待入库完成', startedAt: null, finishedAt: null },
        ]);

        try {
            const uploadRes = await uploadKBFileAPI(file);
            if (!isCurrentIdentity(generation)) return;
            const uploadFinishedAt = Date.now();

            setIngestionSteps((prev) =>
                prev.map((step) =>
                    step.id === 'file-upload'
                        ? {
                            ...step,
                            status: 'done',
                            finishedAt: uploadFinishedAt,
                            durationMs: uploadFinishedAt - now,
                            description: `已成功上传: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`,
                        }
                        : step
                )
            );

            if (uploadRes.deduplicated || uploadRes.task_status === 'completed') {
                const completeTime = Date.now();
                setIngestionSteps((prev) =>
                    prev.map((step) => {
                        if (step.id === 'file-upload') return step;
                        return {
                            ...step,
                            status: 'done',
                            startedAt: step.startedAt ?? uploadFinishedAt,
                            finishedAt: completeTime,
                            description: step.id === 'ingestion-complete'
                                ? '知识库文档秒传匹配成功，入库完成！'
                                : '已完成(秒传缓存)',
                        };
                    })
                );
                setIsIngesting(false);
                message.success('文件入库成功 (秒传匹配)！');

                tabSwitchTimerRef.current = setTimeout(() => {
                    if (!isCurrentIdentity(generation)) return;
                    setActiveTraceTab('rag');
                }, 4000);
                return;
            }

            const taskId = uploadRes.task_id;
            let pollAttempts = 0;
            const maxPollAttempts = 120;

            setIngestionSteps((prev) =>
                prev.map((step) =>
                    step.id === 'content-audit'
                        ? { ...step, status: 'running', startedAt: Date.now() }
                        : step
                )
            );

            const pollOnce = async () => {
                if (!isCurrentIdentity(generation)) {
                    if (pollIntervalRef.current) {
                        clearTimeout(pollIntervalRef.current);
                        pollIntervalRef.current = null;
                    }
                    return;
                }
                if (!pollIntervalRef.current) return;
                pollAttempts++;
                if (pollAttempts > maxPollAttempts) {
                    if (pollIntervalRef.current) clearTimeout(pollIntervalRef.current);
                    pollIntervalRef.current = null;
                    setIsIngesting(false);
                    setIngestionSteps((prev) =>
                        prev.map((step) =>
                            step.status === 'running' || step.status === 'idle'
                                ? { ...step, status: 'error', finishedAt: Date.now(), description: '入库任务查询超时' }
                                : step
                        )
                    );
                    message.error('文件入库超时，请前往后台查看任务状态。');
                    return;
                }

                try {
                    const taskRes = await getKBTaskStatusAPI(taskId);
                    if (!isCurrentIdentity(generation)) return;
                    const currentStatus = taskRes.status.toLowerCase();
                    const progress = taskRes.progress;

                    setIngestionSteps((prev) => {
                        const tickTime = Date.now();
                        return prev.map((step) => {
                            if (step.id === 'file-upload') return step;

                            if (currentStatus === 'completed') {
                                return {
                                    ...step,
                                    status: 'done',
                                    startedAt: step.startedAt ?? tickTime,
                                    finishedAt: step.finishedAt ?? tickTime,
                                    description: step.id === 'ingestion-complete' ? '文档已成功解析、切片并建索入库！' : step.description || '已完成',
                                    metricDetails: step.id === 'vector-index' ? { '入库进度': '100%' } : step.metricDetails,
                                };
                            }

                            if (currentStatus === 'failed') {
                                if (step.id === 'ingestion-complete') {
                                    return {
                                        ...step,
                                        status: 'error',
                                        finishedAt: tickTime,
                                        description: taskRes.error_log || '知识文件入库失败，详细信息见错误日志',
                                    };
                                }
                                if (step.status === 'running' || step.status === 'idle') {
                                    return {
                                        ...step,
                                        status: 'error',
                                        finishedAt: tickTime,
                                        description: '处理中断',
                                    };
                                }
                                return step;
                            }

                            const fileStatusFromPayload = (taskRes.payload?.file_status as string | undefined)?.toUpperCase();

                            if (step.id === 'content-audit') {
                                if (fileStatusFromPayload === 'PARSING' || progress < 30) {
                                    return {
                                        ...step,
                                        status: 'running',
                                        startedAt: step.startedAt ?? tickTime,
                                        description: '正在解析提取文档文本内容...',
                                    };
                                } else {
                                    return {
                                        ...step,
                                        status: 'done',
                                        startedAt: step.startedAt ?? tickTime,
                                        finishedAt: step.finishedAt ?? tickTime,
                                        description: '文档文本内容已成功提取',
                                    };
                                }
                            }

                            if (step.id === 'semantic-chunk') {
                                if (fileStatusFromPayload === 'CHUNKING' || (progress >= 30 && progress < 60)) {
                                    return {
                                        ...step,
                                        status: 'running',
                                        startedAt: step.startedAt ?? tickTime,
                                        description: '正在进行智能文本切片与安全扫描...',
                                    };
                                } else if (progress >= 60 || fileStatusFromPayload === 'READY') {
                                    return {
                                        ...step,
                                        status: 'done',
                                        startedAt: step.startedAt ?? tickTime,
                                        finishedAt: step.finishedAt ?? tickTime,
                                        description: '文本切片及分块安全扫描已完成',
                                    };
                                } else {
                                    return step;
                                }
                            }

                            if (step.id === 'vector-index') {
                                if (progress >= 60 && progress < 100) {
                                    return {
                                        ...step,
                                        status: 'running',
                                        startedAt: step.startedAt ?? tickTime,
                                        description: '正在计算向量嵌入并写入向量数据库...',
                                        metricDetails: { '入库进度': `${progress}%` },
                                    };
                                } else if (progress >= 100 || fileStatusFromPayload === 'READY') {
                                    return {
                                        ...step,
                                        status: 'done',
                                        startedAt: step.startedAt ?? tickTime,
                                        finishedAt: step.finishedAt ?? tickTime,
                                        description: '向量索引构建完成',
                                        metricDetails: { '入库进度': '100%' },
                                    };
                                } else {
                                    return step;
                                }
                            }

                            if (step.id === 'ingestion-complete') {
                                if (progress >= 100 || fileStatusFromPayload === 'READY') {
                                    return {
                                        ...step,
                                        status: 'done',
                                        startedAt: step.startedAt ?? tickTime,
                                        finishedAt: tickTime,
                                        description: '文档入库全生命周期执行完成！',
                                    };
                                } else {
                                    return step;
                                }
                            }

                            return step;
                        });
                    });

                    if (currentStatus === 'completed') {
                        if (pollIntervalRef.current) clearTimeout(pollIntervalRef.current);
                        pollIntervalRef.current = null;
                        setIsIngesting(false);
                        message.success('文件入库成功！');
                        tabSwitchTimerRef.current = setTimeout(() => {
                            if (!isCurrentIdentity(generation)) return;
                            setActiveTraceTab('rag');
                        }, 4000);
                    } else if (currentStatus === 'failed') {
                        if (pollIntervalRef.current) clearTimeout(pollIntervalRef.current);
                        pollIntervalRef.current = null;
                        setIsIngesting(false);
                        message.error(taskRes.error_log || '文件入库失败，请查看右侧诊断！');
                    } else {
                        pollIntervalRef.current = setTimeout(pollOnce, 1000);
                    }

                } catch (err) {
                    console.error('轮询入库任务状态失败:', err);
                    if (!isCurrentIdentity(generation)) return;
                    pollIntervalRef.current = setTimeout(pollOnce, 1000);
                }
            };
            pollIntervalRef.current = setTimeout(pollOnce, 1000);

        } catch (err: unknown) {
            if (!isCurrentIdentity(generation)) return;
            console.error('上传文件失败:', err);
            const errMsg = err instanceof Error ? err.message : '文件上传失败';
            setIsIngesting(false);
            setIngestionSteps((prev) =>
                prev.map((step) => {
                    if (step.id === 'file-upload') {
                        return { ...step, status: 'error', finishedAt: Date.now(), description: `上传失败: ${errMsg}` };
                    }
                    if (step.id === 'ingestion-complete') {
                        return { ...step, status: 'error', finishedAt: Date.now(), description: '处理中断' };
                    }
                    return step;
                })
            );
            message.error(errMsg);
        }
    }, [clearIngestionTimers, isCurrentIdentity, user?.id]);

    return {
        activeSessionId,
        activeSession: displayedActiveSession,
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
