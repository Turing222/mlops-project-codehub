import { authHandlers } from './handlers/auth';
import { userHandlers } from './handlers/users';
import { chatHandlers } from './handlers/chat';
import { creditHandlers } from './handlers/credits';
import { repoAnalysisHandlers } from './handlers/repo-analysis';

export const handlers = [
    ...authHandlers,
    ...userHandlers,
    ...chatHandlers,
    ...creditHandlers,
    ...repoAnalysisHandlers,
];
