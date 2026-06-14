type MockOverrides = Record<string, unknown>;

export function buildMockUser(overrides: MockOverrides = {}) {
    return {
        id: 'user-1',
        username: 'testuser',
        email: 'test@example.com',
        role: 'user',
        is_superuser: false,
        is_active: true,
        max_tokens: 10000,
        used_tokens: 500,
        created_at: '2025-01-15T10:00:00Z',
        updated_at: '2025-01-20T12:00:00Z',
        ...overrides,
    };
}

export function buildMockSuperuser(overrides: MockOverrides = {}) {
    return buildMockUser({
        id: 'admin-1',
        username: 'admin',
        email: 'admin@example.com',
        role: 'admin',
        is_superuser: true,
        is_active: true,
        ...overrides,
    });
}

export function buildMockAuthResponse(overrides: MockOverrides = {}) {
    return {
        access_token: 'mock-jwt-token-abc123',
        token_type: 'bearer',
        ...overrides,
    };
}

export function buildMockSession(overrides: MockOverrides = {}) {
    return {
        id: 'session-1',
        title: 'Test Session',
        user_id: 'user-1',
        total_tokens: 150,
        created_at: '2025-01-20T12:00:00Z',
        updated_at: '2025-01-20T12:30:00Z',
        ...overrides,
    };
}

export function buildMockSessionList(
    sessions: MockOverrides[] = [buildMockSession()],
) {
    return {
        items: sessions,
        total: sessions.length,
        skip: 0,
        limit: 50,
    };
}

export function buildMockMetaEvent(overrides: MockOverrides = {}) {
    return {
        type: 'meta',
        session_id: 'session-1',
        session_title: 'New Chat',
        message_id: 'msg-1',
        ...overrides,
    };
}

export function buildMockChunkEvent(content: string) {
    return { type: 'chunk', content };
}

export function buildMockRawSearchContext(overrides: MockOverrides = {}) {
    return {
        citations: [
            { document_name: 'doc1.pdf', chunk_id: 'c1', score: 0.92, summary: 'Relevant passage from document one.' },
            { document_name: 'report.docx', chunk_id: 'c2', score: 0.78, summary: 'Another passage from the report.' },
        ],
        ...overrides,
    };
}
