import request from '../lib/http/client';
import { parseWithSchema } from '../schemas/parse';
import { 
    knowledgeBaseResponseSchema,
    knowledgeUploadResponseSchema,
    kbTaskResponseSchema,
    knowledgeFilesListSchema
} from '../schemas/chat';
import { API_URLS } from './urls';
import { resolveIdempotencyKey, IDEMPOTENCY_KEY_HEADER } from '../lib/http/idempotency';

export const getDefaultKBAPI = () => {
    return request
        .get<unknown, unknown>(API_URLS.KNOWLEDGE.DEFAULT)
        .then((response) =>
            parseWithSchema(
                knowledgeBaseResponseSchema,
                response,
                '获取默认知识库响应格式无效',
            ),
        );
};

export const uploadKBFileAPI = (file: File, idempotencyKey?: string) => {
    const resolvedKey = resolveIdempotencyKey(idempotencyKey);
    const formData = new FormData();
    formData.append('file', file);
    return request
        .post<unknown, unknown>(API_URLS.KNOWLEDGE.DEFAULT_UPLOAD, formData, {
            headers: {
                [IDEMPOTENCY_KEY_HEADER]: resolvedKey,
            },
        })
        .then((response) =>
            parseWithSchema(
                knowledgeUploadResponseSchema,
                response,
                '文件上传响应格式无效',
            ),
        );
};

export const getKBTaskStatusAPI = (taskId: string) => {
    return request
        .get<unknown, unknown>(API_URLS.KNOWLEDGE.TASK_STATUS(taskId))
        .then((response) =>
            parseWithSchema(
                kbTaskResponseSchema,
                response,
                '获取任务状态响应格式无效',
            ),
        );
};

export const getDefaultKBFilesAPI = () => {
    return request
        .get<unknown, unknown>(API_URLS.KNOWLEDGE.DEFAULT_FILES)
        .then((response) =>
            parseWithSchema(
                knowledgeFilesListSchema,
                response,
                '获取知识库文件列表响应格式无效',
            ),
        );
};

export const deleteKBFileAPI = (fileId: string) => {
    // 204 No Content — no body to validate with parseWithSchema.
    return request.delete<unknown, unknown>(API_URLS.KNOWLEDGE.DELETE_FILE(fileId));
};

