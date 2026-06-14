import { authResponseSchema } from '../../schemas/auth';
import {
    chatMessageSchema,
    chatSessionSchema,
    sessionDetailResponseSchema,
    sessionListResponseSchema,
} from '../../schemas/chat';
import {
    userImportResponseSchema,
    userSchema,
} from '../../schemas/user';
import type { User, AuthResponse, UserImportResponse } from '../../types/user';
import type {
    ChatSession,
    ChatMessage,
    SessionListResponse,
    SessionDetailResponse,
} from '../../types/chat';
import {
    buildMockAuthResponse,
    buildMockSession,
    buildMockSuperuser,
} from '../mock-data';

let userIdCounter = 1;
let sessionIdCounter = 1;
let msgIdCounter = 1;

export function buildUser(overrides: Partial<User> = {}): User {
    const base = buildMockSuperuser({
        id: String(userIdCounter++),
        created_at: '2025-01-01T00:00:00Z',
        updated_at: '2025-01-01T00:00:00Z',
    });
    return userSchema.parse({ ...base, ...overrides });
}

export function buildAuthResponse(overrides: { username?: string } = {}): AuthResponse {
    const user = buildUser({ username: overrides.username ?? 'admin' });
    return authResponseSchema.parse({
        ...buildMockAuthResponse({ access_token: 'test-access-token' }),
        user,
    });
}

export function buildUserImportResponse(
    overrides: Partial<UserImportResponse> = {},
): UserImportResponse {
    return userImportResponseSchema.parse({
        filename: 'users.csv',
        total_rows: 10,
        imported_rows: 10,
        message: '批量导入成功',
        ...overrides,
    });
}

export function buildChatSession(overrides: Partial<ChatSession> = {}): ChatSession {
    const id = String(sessionIdCounter++);
    return chatSessionSchema.parse(buildMockSession({
        id,
        title: `Session ${id}`,
        user_id: '1',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        ...overrides,
    }));
}

export function buildChatMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
    return chatMessageSchema.parse({
        id: `msg-${msgIdCounter++}`,
        session_id: '1',
        role: 'assistant',
        content: 'Hello',
        status: 'success',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        ...overrides,
    });
}

export function buildSessionListResponse(
    overrides: { skip?: number; limit?: number; count?: number } = {},
): SessionListResponse {
    const count = overrides.count ?? 3;
    const items = Array.from({ length: count }, () => buildChatSession());
    return sessionListResponseSchema.parse({
        items,
        total: count,
        skip: overrides.skip ?? 0,
        limit: overrides.limit ?? 50,
    });
}

export function buildSessionDetailResponse(
    sessionId: string,
): SessionDetailResponse {
    const session = buildChatSession({ id: sessionId });
    const messages = [
        buildChatMessage({ session_id: sessionId, role: 'user', content: 'Hello' }),
        buildChatMessage({ session_id: sessionId, role: 'assistant', content: 'Hi there!' }),
    ];
    return sessionDetailResponseSchema.parse({
        session,
        messages,
        total_messages: messages.length,
    });
}

export function resetFactoryCounters() {
    userIdCounter = 1;
    sessionIdCounter = 1;
    msgIdCounter = 1;
}
