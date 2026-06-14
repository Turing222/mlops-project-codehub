import * as z from 'zod';

const requiredString = z.string().trim().min(1);

export const chatSessionSchema = z.object({
    id: requiredString,
    title: requiredString,
    user_id: requiredString,
    kb_id: z.string().nullable().optional(),
    model_config_data: z.record(z.string(), z.unknown()).nullable().optional(),
    total_tokens: z.number().optional(),
    created_at: requiredString,
    updated_at: requiredString,
});

export const chatMessageSchema = z.object({
    id: requiredString,
    session_id: requiredString,
    role: z.enum(['user', 'assistant', 'system']),
    content: z.string(),
    status: z.enum(['thinking', 'streaming', 'success', 'failed']),
    latency_ms: z.number().nullable().optional(),
    search_context: z.record(z.string(), z.unknown()).nullable().optional(),
    message_metadata: z.record(z.string(), z.unknown()).optional(),
    created_at: requiredString,
    updated_at: requiredString,
});

export const chatQueryRequestSchema = z.object({
    query: requiredString,
    session_id: z.string().nullable().optional(),
    kb_id: z.string().nullable().optional(),
    client_request_id: requiredString.optional(),
    enable_external_context: z.boolean().optional(),
});

export const chatQueryResponseSchema = z.object({
    session_id: requiredString,
    session_title: requiredString,
    answer: chatMessageSchema,
});

export const sessionListResponseSchema = z.object({
    items: z.array(chatSessionSchema),
    total: z.number().int().nonnegative(),
    skip: z.number().int().nonnegative(),
    limit: z.number().int().nonnegative(),
});

export const sessionDetailResponseSchema = z.object({
    session: chatSessionSchema,
    messages: z.array(chatMessageSchema),
    total_messages: z.number().int().nonnegative(),
});

export const citationItemSchema = z.object({
    document_name: z.string(),
    chunk_id: z.string(),
    score: z.number().min(0).max(1).optional().default(0),
    summary: z.string().optional().default(''),
});

export const ragMetricsSchema = z.object({
    planner_ms: z.number().optional(),
    retrieve_ms: z.number().optional(),
    rerank_ms: z.number().optional(),
    context_build_ms: z.number().optional(),
    citation_validate_ms: z.number().optional(),
    candidate_count: z.number().optional(),
    hit_count: z.number().optional(),
    retrieval_mode: z.string().optional(),
    planner_used: z.boolean().optional(),
    rerank_used: z.boolean().optional(),
    external_context_ms: z.number().optional(),
    external_context_hit_count: z.number().optional(),
    external_context_used: z.boolean().optional(),
    external_context_provider: z.string().optional(),
    context_mode: z.string().optional(),
    selected_sources: z.string().optional(),
    route_reason: z.string().optional(),
    external_context_planned: z.boolean().optional(),
    planner_refusal: z.boolean().optional(),
    refusal_type: z.string().optional(),
    answer_route: z.string().optional(),
    route_confidence: z.number().optional(),
    planner_refusal_reason: z.string().optional(),
    answer_model_tier: z.string().optional(),
    answer_model_provider: z.string().optional(),
    answer_model_name: z.string().optional(),
    model_route_confidence: z.number().optional(),
    model_route_reason: z.string().optional(),
    model_route_fallback: z.boolean().optional(),
    llm_thinking_ms: z.number().optional(),
    llm_answer_ms: z.number().optional(),
}).partial();

export const chatMessageMetricsSchema = z.object({
    queue_wait_ms: z.number().optional(),
    e2e_first_token_ms: z.number().optional(),
    worker_total_latency_ms: z.number().optional(),
    llm_first_token_ms: z.number().optional(),
    first_token_latency_ms: z.number().optional(),
    llm_generate_ms: z.number().optional(),
    tokens_input: z.number().optional(),
    tokens_output: z.number().optional(),
    tokens_per_second: z.number().optional(),
    answer_model_tier: z.string().optional(),
    answer_model_provider: z.string().optional(),
    answer_model_name: z.string().optional(),
    model_route_confidence: z.number().optional(),
    model_route_reason: z.string().optional(),
    model_route_fallback: z.boolean().optional(),
    llm_thinking_ms: z.number().optional(),
    llm_answer_ms: z.number().optional(),
}).partial();

export const searchContextSchema = z.object({
    citations: z.array(citationItemSchema).optional().default([]),
    metrics: ragMetricsSchema.optional(),
});

export const chatStreamMetaEventSchema = z.object({
    type: z.literal('meta'),
    session_id: requiredString,
    session_title: requiredString,
    message_id: z.string().optional(),
});

export const chatStreamChunkEventSchema = z.object({
    type: z.literal('chunk'),
    content: z.string(),
});

export const chatStreamErrorEventSchema = z.object({
    type: z.literal('error'),
    message: z.string().optional(),
});

export const chatStreamStartedEventSchema = z.object({
    type: z.literal('started'),
});

export const chatStreamEventSchema = z.discriminatedUnion('type', [
    chatStreamStartedEventSchema,
    chatStreamMetaEventSchema,
    chatStreamChunkEventSchema,
    chatStreamErrorEventSchema,
]);

export type ChatSession = z.infer<typeof chatSessionSchema>;
export type ChatMessage = z.infer<typeof chatMessageSchema>;
export type ChatQueryRequest = z.infer<typeof chatQueryRequestSchema>;
export type ChatQueryResponse = z.infer<typeof chatQueryResponseSchema>;
export type SessionListResponse = z.infer<typeof sessionListResponseSchema>;
export type SessionDetailResponse = z.infer<typeof sessionDetailResponseSchema>;
export type ChatStreamEvent = z.infer<typeof chatStreamEventSchema>;
export type ChatMessageMetrics = z.infer<typeof chatMessageMetricsSchema>;
export type RagMetrics = z.infer<typeof ragMetricsSchema>;

export const knowledgeBaseResponseSchema = z.object({
    id: requiredString,
    name: requiredString,
});

export type KnowledgeBaseResponse = z.infer<typeof knowledgeBaseResponseSchema>;

export const knowledgeUploadResponseSchema = z.object({
    task_id: requiredString,
    file_id: requiredString,
    kb_id: z.string().nullable().optional(),
    file_status: z.string(),
    task_status: z.string(),
    deduplicated: z.boolean().optional().default(false),
});

export type KnowledgeUploadResponse = z.infer<typeof knowledgeUploadResponseSchema>;

export const kbTaskResponseSchema = z.object({
    id: requiredString,
    action_type: z.string(),
    status: z.string(),
    progress: z.number().int(),
    payload: z.record(z.string(), z.unknown()),
    error_log: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
});

export type KBTaskResponse = z.infer<typeof kbTaskResponseSchema>;

export const knowledgeFileSchema = z.object({
    id: requiredString,
    kb_id: requiredString,
    filename: requiredString,
    file_size: z.number().int(),
    content_sha256: z.string().nullable().optional(),
    status: z.string(),
    created_at: requiredString,
    updated_at: requiredString,
});

export const knowledgeFilesListSchema = z.array(knowledgeFileSchema);

export type KnowledgeFile = z.infer<typeof knowledgeFileSchema>;
