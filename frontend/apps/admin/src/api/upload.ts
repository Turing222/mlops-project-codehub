import request from '../lib/http/client';
import { parseWithSchema } from '../schemas/parse';
import { userImportResponseSchema } from '../schemas/user';
import { API_URLS } from './urls';

export const uploadCSVAPI = (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return request
        .post<unknown, unknown>(API_URLS.USER.CSV_UPLOAD, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        })
        .then((response) => parseWithSchema(userImportResponseSchema, response, '文件上传响应格式无效'));
};
