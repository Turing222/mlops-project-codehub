import { describe, expect, it } from 'vitest';
import { authKeys } from './auth';
import { chatKeys } from './chat';
import { knowledgeKeys } from './knowledge';
import { userKeys } from './users';

describe('query-keys', () => {
    describe('authKeys', () => {
        it('all returns ["auth"]', () => {
            expect(authKeys.all()).toEqual(['auth']);
        });

        it('me extends all with "me"', () => {
            const all = authKeys.all();
            const me = authKeys.me();
            expect(me).toEqual([...all, 'me']);
        });
    });

    describe('chatKeys', () => {
        it('all returns ["chat"]', () => {
            expect(chatKeys.all()).toEqual(['chat']);
        });

        it('sessions extends all with "sessions"', () => {
            const all = chatKeys.all();
            const sessions = chatKeys.sessions();
            expect(sessions).toEqual([...all, 'sessions']);
        });

        it('sessionDetail includes session id', () => {
            expect(chatKeys.sessionDetail('abc')).toEqual(['chat', 'session', 'abc']);
        });
    });

    describe('userKeys', () => {
        it('all returns ["users"]', () => {
            expect(userKeys.all()).toEqual(['users']);
        });

        it('query includes params object', () => {
            expect(userKeys.query({ username: 'alice' })).toEqual([
                'users',
                'query',
                { username: 'alice' },
            ]);
        });
    });

    describe('knowledgeKeys', () => {
        it('all returns ["knowledge"]', () => {
            expect(knowledgeKeys.all()).toEqual(['knowledge']);
        });

        it('default extends all with "default"', () => {
            expect(knowledgeKeys.default()).toEqual(['knowledge', 'default']);
        });

        it('files extends all with "files"', () => {
            expect(knowledgeKeys.files()).toEqual(['knowledge', 'files']);
        });

        it('task places task id at the end', () => {
            expect(knowledgeKeys.task('task-1')).toEqual(['knowledge', 'task', 'task-1']);
        });
    });

    describe('cross-domain isolation', () => {
        it('top-level keys do not collide', () => {
            const roots = [
                authKeys.all()[0],
                chatKeys.all()[0],
                userKeys.all()[0],
                knowledgeKeys.all()[0],
            ];
            expect(new Set(roots).size).toBe(4);
        });

        it('sessionDetail keys are unique per session id', () => {
            expect(chatKeys.sessionDetail('a')).not.toEqual(chatKeys.sessionDetail('b'));
        });

        it('user query keys are unique per params', () => {
            expect(userKeys.query({ username: 'x' })).not.toEqual(
                userKeys.query({ username: 'y' }),
            );
        });
    });
});
