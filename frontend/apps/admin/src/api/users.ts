import request from '../lib/http/client';
import { parseWithSchema } from '../schemas/parse';
import {
    userImportResponseSchema,
    userQueryParamsSchema,
    userRegistrationPayloadSchema,
    userSchema,
    userUpdatePayloadSchema,
} from '../schemas/user';
import { API_URLS } from './urls';
import type {
    UserRegistrationPayload,
    UserUpdatePayload,
} from '../types/user';

export const queryUserAPI = (params: { username?: string; email?: string }) => {
    return request
        .get<unknown, unknown>(API_URLS.USER.QUERY, { params: userQueryParamsSchema.parse(params) })
        .then((response) => parseWithSchema(userSchema, response, '用户查询响应格式无效'));
};

export const updateUserAPI = (id: string | number, data: UserUpdatePayload) =>
    request
        .patch<unknown, unknown>(API_URLS.USER.UPDATE(id), userUpdatePayloadSchema.parse(data))
        .then((response) => parseWithSchema(userSchema, response, '用户更新响应格式无效'));

export const registerUserAPI = (data: UserRegistrationPayload) =>
    request
        .post<unknown, unknown>(API_URLS.AUTH.REGISTER, userRegistrationPayloadSchema.parse(data))
        .then((response) => parseWithSchema(userSchema, response, '用户创建响应格式无效'));

export const uploadUsersCSVAPI = (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return request
        .post<unknown, unknown>(API_URLS.USER.CSV_UPLOAD, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        })
        .then((response) =>
            parseWithSchema(userImportResponseSchema, response, '批量导入响应格式无效'),
        );
};
