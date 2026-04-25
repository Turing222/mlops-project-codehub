import * as z from 'zod';

const requiredString = z.string().trim().min(1);

export const userSchema = z.object({
    id: z.union([z.string(), z.number()]),
    username: requiredString,
    email: z.email().optional(),
    role: z.enum(['user', 'admin']).optional(),
    avatar: z.string().optional(),
    is_superuser: z.boolean().optional(),
    is_active: z.boolean().optional(),
    max_tokens: z.number().int().nonnegative().optional(),
    used_tokens: z.number().int().nonnegative().optional(),
    created_at: z.string().optional(),
    updated_at: z.string().optional(),
});

export const userRegistrationPayloadSchema = z
    .object({
        username: requiredString,
        email: z.email(),
        password: z.string().min(8),
        confirm_password: z.string().min(8),
        max_tokens: z.number().int().nonnegative().optional(),
    })
    .refine((data) => data.password === data.confirm_password, {
        message: '两次输入的密码不一致',
        path: ['confirm_password'],
    });

export const userUpdatePayloadSchema = z.object({
    username: requiredString.optional(),
    email: z.email().optional(),
    password: z.string().min(8).optional(),
    is_active: z.boolean().optional(),
    max_tokens: z.number().int().nonnegative().optional(),
});

export const userImportResponseSchema = z.object({
    filename: requiredString,
    total_rows: z.number().int().nonnegative(),
    imported_rows: z.number().int().nonnegative(),
    message: requiredString,
});

export const userQueryParamsSchema = z
    .object({
        username: requiredString.optional(),
        email: z.email().optional(),
    })
    .refine((data) => Boolean(data.username || data.email), {
        message: 'username 或 email 至少提供一个',
    });

export type User = z.infer<typeof userSchema>;
export type UserRegistrationPayload = z.infer<typeof userRegistrationPayloadSchema>;
export type UserUpdatePayload = z.infer<typeof userUpdatePayloadSchema>;
export type UserImportResponse = z.infer<typeof userImportResponseSchema>;
export type UserQueryParams = z.infer<typeof userQueryParamsSchema>;
