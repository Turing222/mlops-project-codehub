import * as z from 'zod';

import { userSchema } from './user';

const requiredString = z.string().trim().min(1);

export const loginCredentialsSchema = z.object({
    username: requiredString,
    password: requiredString,
});

export const authResponseSchema = z.object({
    access_token: requiredString,
    token_type: requiredString,
    user: userSchema.optional(),
});

export type LoginCredentials = z.infer<typeof loginCredentialsSchema>;
export type AuthResponse = z.infer<typeof authResponseSchema>;
