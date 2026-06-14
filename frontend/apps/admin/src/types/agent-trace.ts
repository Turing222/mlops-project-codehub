import {
    chatMessageMetricsSchema,
    ragMetricsSchema,
    searchContextSchema,
} from '../schemas/chat';
import type { ChatMessageMetrics, RagMetrics } from '../schemas/chat';

export type AgentTraceStepStatus = 'idle' | 'running' | 'done' | 'skipped' | 'error';
type ModelRouteMetricKey =
    | 'answer_model_tier'
    | 'answer_model_provider'
    | 'answer_model_name'
    | 'model_route_confidence'
    | 'model_route_reason'
    | 'model_route_fallback';

export interface AgentTraceStep {
    id: string;
    status: AgentTraceStepStatus;
    description: string;
    startedAt: number | null;
    finishedAt: number | null;
    durationMs?: number;
    metricDetails?: Record<string, number | string | boolean>;
}

export interface CitationItem {
    documentName: string;
    chunkId: string;
    relevanceScore: number;
    summarySnippet: string;
    chunkIndex?: number;
    metaInfo?: Record<string, unknown>;
    url?: string;
    provider?: string;
    scoreKind?: string;
    rerankScore?: number;
}

export interface AgentTraceState {
    steps: AgentTraceStep[];
    citations: CitationItem[];
    isComplete: boolean;
}

export const TRACE_STEP_DEFS = [
    { id: 'receive-query' },
    { id: 'router-judge' },
    { id: 'kb-search' },
    { id: 'local-search' },
    { id: 'web-search' },
    { id: 'model-thinking' },
    { id: 'generate-answer' },
    { id: 'organize-citations' },
    { id: 'complete' },
] as const;

export function createInitialTraceSteps(): AgentTraceStep[] {
    const now = Date.now();
    return TRACE_STEP_DEFS.map((def, index) => ({
        id: def.id,
        status: index === 0 ? ('running' as const) : ('idle' as const),
        description: '',
        startedAt: index === 0 ? now : null,
        finishedAt: null,
    }));
}

export const INGESTION_TRACE_STEP_DEFS = [
    { id: 'file-upload' },
    { id: 'content-audit' },
    { id: 'semantic-chunk' },
    { id: 'vector-index' },
    { id: 'ingestion-complete' },
] as const;

export function createInitialIngestionSteps(): AgentTraceStep[] {
    return INGESTION_TRACE_STEP_DEFS.map((def) => ({
        id: def.id,
        status: 'idle' as const,
        description: '',
        startedAt: null,
        finishedAt: null,
    }));
}

function parseMetrics<T>(
    payload: Record<string, unknown> | null | undefined,
    parser: { safeParse: (value: unknown) => { success: true; data: T } | { success: false } },
): T | undefined {
    const metrics = payload?.metrics;
    if (!metrics || typeof metrics !== 'object') return undefined;
    const result = parser.safeParse(metrics);
    return result.success ? result.data : undefined;
}

export function parseChatMessageMetrics(
    messageMetadata: Record<string, unknown> | null | undefined,
): ChatMessageMetrics | undefined {
    return parseMetrics(messageMetadata, chatMessageMetricsSchema);
}

export function parseRagMetrics(
    searchContext: Record<string, unknown> | null | undefined,
): RagMetrics | undefined {
    return parseMetrics(searchContext, ragMetricsSchema);
}

function hasAnyMetric(
    messageMetrics?: ChatMessageMetrics,
    ragMetrics?: RagMetrics,
): boolean {
    return Boolean(
        (messageMetrics && Object.keys(messageMetrics).length > 0) ||
        (ragMetrics && Object.keys(ragMetrics).length > 0),
    );
}

function pickModelRouteMetric(
    key: ModelRouteMetricKey,
    messageMetrics?: ChatMessageMetrics,
    ragMetrics?: RagMetrics,
) {
    // Message metadata reflects the final generation model; RAG metrics are
    // retained as a fallback for older records or pre-generation traces.
    return messageMetrics?.[key] ?? ragMetrics?.[key];
}

export function applyTraceMetricsToSteps(
    steps: AgentTraceStep[],
    messageMetrics?: ChatMessageMetrics,
    ragMetrics?: RagMetrics,
): AgentTraceStep[] {
    if (!hasAnyMetric(messageMetrics, ragMetrics)) return steps;

    const baseSteps = steps.length > 0
        ? steps
        : createInitialTraceSteps().map((step) => ({
            ...step,
            status: 'done' as const,
            finishedAt: Date.now(),
        }));

    const isRefusal = Boolean(ragMetrics?.planner_refusal || ragMetrics?.answer_route === 'refuse');

    return baseSteps.map((step) => {
        if (step.id === 'receive-query') {
            return {
                ...step,
                durationMs: step.durationMs ?? messageMetrics?.queue_wait_ms,
                description: step.description || (messageMetrics?.queue_wait_ms !== undefined ? '服务器调度与队列等待' : step.description),
            };
        }
        if (step.id === 'router-judge') {
            const metricDetails: Record<string, number | string | boolean> = {};
            if (ragMetrics?.planner_used !== undefined) {
                metricDetails.planner_used = ragMetrics.planner_used;
            }
            if (ragMetrics?.context_mode !== undefined) {
                metricDetails.context_mode = ragMetrics.context_mode;
            }
            if (ragMetrics?.selected_sources !== undefined) {
                metricDetails.selected_sources = ragMetrics.selected_sources;
            }
            if (ragMetrics?.route_reason !== undefined) {
                metricDetails.route_reason = ragMetrics.route_reason;
            }
            if (ragMetrics?.external_context_planned !== undefined) {
                metricDetails.external_context_planned = ragMetrics.external_context_planned;
            }
            if (ragMetrics?.answer_route !== undefined) {
                metricDetails.answer_route = ragMetrics.answer_route;
            }
            if (ragMetrics?.route_confidence !== undefined) {
                metricDetails.route_confidence = ragMetrics.route_confidence;
            }
            if (ragMetrics?.planner_refusal !== undefined) {
                metricDetails.planner_refusal = ragMetrics.planner_refusal;
            }
            if (ragMetrics?.planner_refusal_reason !== undefined) {
                metricDetails.planner_refusal_reason = ragMetrics.planner_refusal_reason;
            }
            return {
                ...step,
                durationMs: ragMetrics?.planner_ms,
                metricDetails: Object.keys(metricDetails).length > 0 ? metricDetails : step.metricDetails,
            };
        }
        const selected = ragMetrics?.selected_sources ? ragMetrics.selected_sources.split(',') : [];
        const isKbActive = ragMetrics?.planner_used === false
            ? true
            : (ragMetrics?.selected_sources ? selected.includes('kb') : (ragMetrics?.retrieve_ms !== undefined || ragMetrics?.candidate_count !== undefined));
        const isWebActive = ragMetrics?.planner_used === false
            ? true
            : (ragMetrics?.selected_sources ? selected.includes('web') : (ragMetrics?.external_context_ms !== undefined || ragMetrics?.external_context_hit_count !== undefined));

        if (step.id === 'kb-search') {
            if (isRefusal || !isKbActive) {
                return { ...step, status: 'skipped' as const, finishedAt: Date.now() };
            }
            const metricDetails: Record<string, number | string | boolean> = {};
            const rerankUsed = ragMetrics?.rerank_used === true;

            if (rerankUsed) {
                if (ragMetrics?.candidate_count !== undefined) {
                    metricDetails.candidate_count = ragMetrics.candidate_count;
                }
                if (ragMetrics?.hit_count !== undefined) {
                    metricDetails.hit_count = ragMetrics.hit_count;
                }
            } else {
                if (ragMetrics?.hit_count !== undefined) {
                    metricDetails.hit_count = ragMetrics.hit_count;
                } else if (ragMetrics?.candidate_count !== undefined) {
                    metricDetails.hit_count = ragMetrics.candidate_count;
                }
            }

            if (ragMetrics?.retrieval_mode !== undefined) {
                metricDetails.retrieval_mode = ragMetrics.retrieval_mode;
            }
            if (ragMetrics?.rerank_used !== undefined) {
                metricDetails.rerank_used = ragMetrics.rerank_used;
            }
            if (rerankUsed && ragMetrics?.rerank_ms !== undefined) {
                metricDetails.rerank_ms = ragMetrics.rerank_ms;
            }
            return {
                ...step,
                durationMs: ragMetrics?.retrieve_ms,
                metricDetails: Object.keys(metricDetails).length > 0 ? metricDetails : step.metricDetails,
            };
        }
        if (step.id === 'local-search') {
            return { ...step, status: 'skipped' as const, finishedAt: Date.now() };
        }
        if (step.id === 'web-search') {
            if (isRefusal || !isWebActive) {
                return { ...step, status: 'skipped' as const, finishedAt: Date.now() };
            }
            const metricDetails: Record<string, number | string | boolean> = {};
            if (ragMetrics?.external_context_hit_count !== undefined) {
                metricDetails.external_context_hit_count = ragMetrics.external_context_hit_count;
            }
            if (ragMetrics?.external_context_provider !== undefined) {
                metricDetails.external_context_provider = ragMetrics.external_context_provider;
            }
            return {
                ...step,
                durationMs: ragMetrics?.external_context_ms,
                metricDetails: Object.keys(metricDetails).length > 0 ? metricDetails : step.metricDetails,
            };
        }
        if (step.id === 'model-thinking') {
            const hasThinkingMetric = messageMetrics?.llm_thinking_ms !== undefined;
            const thinkingMs = messageMetrics?.llm_thinking_ms;
            const isReasoning = messageMetrics?.answer_model_tier === 'reasoning';

            if (hasThinkingMetric) {
                if (!thinkingMs || thinkingMs === 0) {
                    return {
                        ...step,
                        status: 'skipped' as const,
                        finishedAt: Date.now(),
                        durationMs: undefined,
                    };
                }
                return {
                    ...step,
                    status: 'done' as const,
                    finishedAt: Date.now(),
                    durationMs: thinkingMs,
                };
            }

            // Fallback for older records without llm_thinking_ms metric:
            // Skip model-thinking if model tier is explicitly known and is NOT 'reasoning'.
            if (messageMetrics?.answer_model_tier !== undefined && !isReasoning) {
                return {
                    ...step,
                    status: 'skipped' as const,
                    finishedAt: Date.now(),
                    durationMs: undefined,
                };
            }

            // Otherwise, fallback to using firstToken as thinking time for backward compatibility
            const firstToken = messageMetrics?.llm_first_token_ms ?? messageMetrics?.first_token_latency_ms;
            if (firstToken === undefined) {
                return step;
            }
            return {
                ...step,
                status: 'done' as const,
                finishedAt: Date.now(),
                durationMs: firstToken,
            };
        }
        if (step.id === 'generate-answer') {
            const metricDetails: Record<string, number | string | boolean> = {};
            // Prefer Web-observed e2e latency when available; fall back to the
            // Worker-local first token latency for older/completed records.
            const firstToken = messageMetrics?.e2e_first_token_ms ?? messageMetrics?.first_token_latency_ms;
            if (firstToken !== undefined) metricDetails.first_token_latency_ms = firstToken;
            if (messageMetrics?.llm_first_token_ms !== undefined) {
                metricDetails.llm_first_token_ms = messageMetrics.llm_first_token_ms;
            }
            const modelRouteKeys: ModelRouteMetricKey[] = [
                'answer_model_tier',
                'answer_model_provider',
                'answer_model_name',
                'model_route_confidence',
                'model_route_reason',
                'model_route_fallback',
            ];
            for (const key of modelRouteKeys) {
                const value = pickModelRouteMetric(key, messageMetrics, ragMetrics);
                if (value !== undefined) {
                    metricDetails[key] = value;
                }
            }

            // Prefer the precise llm_answer_ms metric when available.
            let actualGenerateMs = messageMetrics?.llm_answer_ms;
            if (actualGenerateMs === undefined) {
                // Fallback for older/completed records.
                const llmGenerateMs = messageMetrics?.llm_generate_ms;
                const llmFirstToken = messageMetrics?.llm_first_token_ms ?? messageMetrics?.first_token_latency_ms ?? 0;
                actualGenerateMs = llmGenerateMs !== undefined
                    ? Math.max(0, llmGenerateMs - llmFirstToken)
                    : undefined;
            }

            return {
                ...step,
                durationMs: actualGenerateMs,
                metricDetails: Object.keys(metricDetails).length > 0 ? metricDetails : step.metricDetails,
            };
        }
        if (step.id === 'organize-citations') {
            if (isRefusal) {
                return { ...step, status: 'skipped' as const, finishedAt: Date.now() };
            }
            if (ragMetrics?.citation_validate_ms !== undefined) {
                return { ...step, durationMs: ragMetrics.citation_validate_ms };
            }
            return step;
        }
        if (step.id === 'complete') {
            const metricDetails: Record<string, number | string | boolean> = {};
            if (messageMetrics?.tokens_per_second !== undefined) {
                metricDetails.tokens_per_second = messageMetrics.tokens_per_second;
            }
            if (messageMetrics?.queue_wait_ms !== undefined) {
                metricDetails.queue_wait_ms = messageMetrics.queue_wait_ms;
            }
            return {
                ...step,
                durationMs: messageMetrics?.worker_total_latency_ms,
                metricDetails: Object.keys(metricDetails).length > 0 ? metricDetails : step.metricDetails,
            };
        }
        return step;
    });
}

export function parseCitations(
    searchContext: Record<string, unknown> | undefined,
): CitationItem[] {
    if (!searchContext || typeof searchContext !== 'object') return [];

    // Support real backend RAG refs structure
    if (searchContext.refs && Array.isArray(searchContext.refs)) {
        const items: CitationItem[] = [];
        for (const ref of searchContext.refs) {
            if (ref && typeof ref === 'object') {
                const filename = (
                    (ref.title as string) ||
                    (ref.filename as string) ||
                    (ref.url as string) ||
                    (ref.file_id as string) ||
                    'Unknown File'
                );
                if (ref.chunks && Array.isArray(ref.chunks)) {
                    for (const ch of ref.chunks) {
                        if (ch && typeof ch === 'object') {
                            items.push({
                                documentName: filename,
                                chunkId: (ch.ref_id as string) || (ch.chunk_id as string) || '',
                                relevanceScore: typeof ch.score === 'number' ? ch.score : 0,
                                summarySnippet: (ch.text as string) || (ch.content as string) || '',
                                chunkIndex: typeof ch.chunk_index === 'number' ? ch.chunk_index : undefined,
                                metaInfo: (ch.meta_info && typeof ch.meta_info === 'object') ? ch.meta_info as Record<string, unknown> : undefined,
                                url: (ch.url as string) || (ref.url as string) || undefined,
                                provider: (ch.provider as string) || (ref.provider as string) || undefined,
                                scoreKind: (ch.score_kind as string) || undefined,
                                rerankScore: typeof ch.rerank_score === 'number' ? ch.rerank_score : undefined,
                            });
                        }
                    }
                }
            }
        }
        return items;
    }

    // Fallback to mock flat citations
    const result = searchContextSchema.safeParse(searchContext);
    if (result.success && result.data.citations) {
        return result.data.citations
            .map((raw): CitationItem => ({
                documentName: raw.document_name,
                chunkId: raw.chunk_id,
                relevanceScore: raw.score,
                summarySnippet: raw.summary,
            }))
            .filter((c) => c.documentName || c.summarySnippet);
    }

    return [];
}
