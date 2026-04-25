import request from '../lib/http/client';
import { authResponseSchema, loginCredentialsSchema } from '../schemas/auth';
import { parseWithSchema } from '../schemas/parse';
import { userRegistrationPayloadSchema, userSchema } from '../schemas/user';
import type { LoginCredentials, UserRegistrationPayload } from '../types/user';
import { API_URLS } from './urls';

export const loginAPI = (data: LoginCredentials) => {
    const payload = loginCredentialsSchema.parse(data);
    // 1. 创建表单转换对象
    const params = new URLSearchParams();

    // 2. 将普通的 JSON 字段填入表单中
    // 这里的 'username' 和 'password' 必须和后端 OAuth2PasswordRequestForm 定义的一致
    params.append('username', payload.username);
    params.append('password', payload.password);

    // 3. 发送转换后的 params
    // Axios 识别到 URLSearchParams 后，会自动将 Content-Type 设为 application/x-www-form-urlencoded
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
