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

export const smsSendRequestSchema = z.object({
    phone: z.string().regex(/^\+?\d{7,15}$/),
});

export const smsLoginRequestSchema = z.object({
    phone: z.string().regex(/^\+?\d{7,15}$/),
    code: z.string().length(6),
});

export const smsSendResponseSchema = z.object({
    message: z.string(),
    code: z.string().optional(),
});

export const googleCallbackRequestSchema = z.object({
    code: z.string().min(1),
    redirect_uri: z.string().min(1),
});

export type LoginCredentials = z.infer<typeof loginCredentialsSchema>;
export type AuthResponse = z.infer<typeof authResponseSchema>;
export type SMSSendRequest = z.infer<typeof smsSendRequestSchema>;
export type SMSLoginRequest = z.infer<typeof smsLoginRequestSchema>;
export type SMSSendResponse = z.infer<typeof smsSendResponseSchema>;
export type GoogleCallbackRequest = z.infer<typeof googleCallbackRequestSchema>;
