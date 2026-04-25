import * as z from 'zod';

const requiredString = z.string().trim().min(1);

export const chatSessionSchema = z.object({
    id: requiredString,
    title: requiredString,
    user_id: requiredString,
    kb_id: z.string().optional(),
    model_config_data: z.record(z.string(), z.unknown()).optional(),
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
    latency_ms: z.number().optional(),
    search_context: z.record(z.string(), z.unknown()).optional(),
    created_at: requiredString,
    updated_at: requiredString,
});

export const chatQueryRequestSchema = z.object({
    query: requiredString,
    session_id: z.string().nullable().optional(),
    kb_id: z.string().nullable().optional(),
    client_request_id: requiredString.optional(),
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

export const chatStreamEventSchema = z.discriminatedUnion('type', [
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
