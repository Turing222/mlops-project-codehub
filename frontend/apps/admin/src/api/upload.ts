import request from '../lib/http/client';
import { parseWithSchema } from '../schemas/parse';
import { userImportResponseSchema } from '../schemas/user';
import { API_URLS } from './urls';
import { resolveIdempotencyKey, IDEMPOTENCY_KEY_HEADER } from '../lib/http/idempotency';

export const uploadCSVAPI = (file: File, idempotencyKey?: string) => {
    const resolvedKey = resolveIdempotencyKey(idempotencyKey);
    const formData = new FormData();
    formData.append('file', file);
    return request
        .post<unknown, unknown>(API_URLS.USER.CSV_UPLOAD, formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
                [IDEMPOTENCY_KEY_HEADER]: resolvedKey,
            },
        })
        .then((response) => parseWithSchema(userImportResponseSchema, response, '文件上传响应格式无效'));
};
