import {
    chatMessageSchema,
    chatSessionSchema,
    chatStreamEventSchema,
    searchContextSchema,
} from './chat';
import { userRegistrationPayloadSchema } from './user';
import {
    creditAccountResponseSchema,
    checkinResponseSchema,
    creditTransactionResponseSchema,
} from './credit';

describe('schema layer', () => {
    it('validates user registration payloads before requests are sent', () => {
        const result = userRegistrationPayloadSchema.safeParse({
            username: 'alice',
            email: 'alice@example.com',
            password: 'password123',
            confirm_password: 'password123',
            max_tokens: 100000,
        });

        expect(result.success).toBe(true);
    });

    it('parses chat stream meta events from the backend', () => {
        const result = chatStreamEventSchema.safeParse({
            type: 'meta',
            session_id: 'session-1',
            session_title: 'Hello',
            message_id: 'message-1',
        });

        expect(result.success).toBe(true);
    });

    it('successfully parses chatSessionSchema when kb_id is null', () => {
        const result = chatSessionSchema.safeParse({
            id: 's1',
            title: 'Test Session',
            user_id: 'u1',
            kb_id: null,
            created_at: '2026-05-21T12:00:00Z',
            updated_at: '2026-05-21T12:00:00Z',
        });
        expect(result.success).toBe(true);
    });

    it('successfully parses chatMessageSchema when latency_ms and search_context are null', () => {
        const result = chatMessageSchema.safeParse({
            id: 'm1',
            session_id: 's1',
            role: 'assistant',
            content: 'Hello world',
            status: 'success',
            latency_ms: null,
            search_context: null,
            created_at: '2026-05-21T12:00:00Z',
            updated_at: '2026-05-21T12:00:00Z',
        });
        expect(result.success).toBe(true);
    });

    it('parses chat message and RAG metrics when present', () => {
        const message = chatMessageSchema.parse({
            id: 'm1',
            session_id: 's1',
            role: 'assistant',
            content: 'Hello world',
            status: 'success',
            latency_ms: 123,
            search_context: {
                metrics: {
                    retrieve_ms: 42,
                    hit_count: 4,
                    retrieval_mode: 'hybrid',
                    rerank_used: true,
                    answer_model_tier: 'fast',
                    model_route_confidence: 0.91,
                },
            },
            message_metadata: {
                metrics: {
                    first_token_latency_ms: 250,
                    tokens_per_second: 12.5,
                    answer_model_name: 'deepseek-v4-flash',
                },
            },
            created_at: '2026-05-21T12:00:00Z',
            updated_at: '2026-05-21T12:00:00Z',
        });
        const searchContext = searchContextSchema.parse(message.search_context);

        expect(message.message_metadata?.metrics).toEqual({
            first_token_latency_ms: 250,
            tokens_per_second: 12.5,
            answer_model_name: 'deepseek-v4-flash',
        });
        expect(searchContext.metrics?.retrieval_mode).toBe('hybrid');
        expect(searchContext.metrics?.answer_model_tier).toBe('fast');
    });

    describe('credit schema', () => {
        it('parses credit account response', () => {
            const result = creditAccountResponseSchema.safeParse({
                id: '88888888-8888-4888-8888-888888888888',
                user_id: '11111111-1111-4111-a111-111111111111',
                balance: 1000,
                is_checked_in_today: true,
                created_at: '2026-05-22T12:00:00Z',
                updated_at: '2026-05-22T12:00:00Z',
            });
            expect(result.success).toBe(true);
        });

        it('parses checkin response', () => {
            const result = checkinResponseSchema.safeParse({
                success: true,
                balance: 600,
                amount_earned: 100,
                expires_at: '2026-06-22T12:00:00Z',
            });
            expect(result.success).toBe(true);
        });

        it('parses credit transaction response', () => {
            const result = creditTransactionResponseSchema.safeParse({
                id: '22222222-2222-4222-a222-222222222222',
                account_id: '88888888-8888-4888-8888-888888888888',
                amount: 100,
                source: 'checkin',
                expires_at: '2026-06-22T12:00:00Z',
                idempotency_key: 'key-1',
                created_at: '2026-05-22T12:00:00Z',
            });
            expect(result.success).toBe(true);
        });
    });
});
