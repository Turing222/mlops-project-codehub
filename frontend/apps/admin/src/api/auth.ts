import * as z from 'zod';

import request from '../lib/http/client';
import {
    authResponseSchema,
    googleCallbackRequestSchema,
    loginCredentialsSchema,
    smsLoginRequestSchema,
    smsSendRequestSchema,
    smsSendResponseSchema,
} from '../schemas/auth';
import { parseWithSchema } from '../schemas/parse';
import { userRegistrationPayloadSchema, userSchema } from '../schemas/user';
import type { LoginCredentials, UserRegistrationPayload } from '../types/user';
import { API_URLS } from './urls';

export const loginAPI = (data: LoginCredentials) => {
    const payload = loginCredentialsSchema.parse(data);
    const params = new URLSearchParams();
    params.append('username', payload.username);
    params.append('password', payload.password);
    return request
        .post<unknown, unknown>(API_URLS.AUTH.LOGIN, params)
        .then((response) => parseWithSchema(authResponseSchema, response, '登录响应格式无效'));
};

export const registerAPI = (data: UserRegistrationPayload) =>
    request
        .post<unknown, unknown>(API_URLS.AUTH.REGISTER, userRegistrationPayloadSchema.parse(data))
        .then((response) => parseWithSchema(userSchema, response, '注册响应格式无效'));

export const getUserProfileAPI = () =>
    request
        .get<unknown, unknown>(API_URLS.USER.ME)
        .then((response) => parseWithSchema(userSchema, response, '用户信息响应格式无效'));

export const updateUserProfileAPI = (data: { username?: string; email?: string; phone?: string }) =>
    request
        .patch<unknown, unknown>(API_URLS.USER.ME, data)
        .then((response) => parseWithSchema(userSchema, response, '更新个人信息响应格式无效'));

// ── SMS Verification ──────────────────────────────────────────

export const sendSMSCodeAPI = (phone: string) => {
    smsSendRequestSchema.parse({ phone });
    return request
        .post<unknown, unknown>(API_URLS.AUTH.SMS_SEND, { phone })
        .then((response) =>
            parseWithSchema(
                smsSendResponseSchema,
                response,
                '发送验证码响应格式无效',
            ),
        );
};

export const smsLoginAPI = (data: { phone: string; code: string }) => {
    smsLoginRequestSchema.parse(data);
    return request
        .post<unknown, unknown>(API_URLS.AUTH.SMS_LOGIN, data)
        .then((response) => parseWithSchema(authResponseSchema, response, '短信登录响应格式无效'));
};

// ── Google OAuth ───────────────────────────────────────────────

export const getGoogleAuthUrlAPI = (redirectUri: string) =>
    request
        .get<unknown, unknown>(API_URLS.AUTH.GOOGLE_URL, { params: { redirect_uri: redirectUri } })
        .then((response) =>
            parseWithSchema(
                z.object({ url: z.string() }),
                response,
                '获取 Google 授权 URL 响应格式无效',
            ),
        );

export const googleCallbackAPI = (data: { code: string; redirect_uri: string }) => {
    googleCallbackRequestSchema.parse(data);
    return request
        .post<unknown, unknown>(API_URLS.AUTH.GOOGLE_CALLBACK, data)
        .then((response) => parseWithSchema(authResponseSchema, response, 'Google 登录响应格式无效'));
};
