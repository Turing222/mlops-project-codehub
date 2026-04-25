import { describe, expect, it } from 'vitest';

import { chatStreamEventSchema } from './chat';
import { userRegistrationPayloadSchema } from './user';

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
});
