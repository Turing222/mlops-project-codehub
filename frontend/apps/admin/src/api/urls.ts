const API_PREFIX = '/api/v1';

const normalizeApiBaseUrl = (value: string | undefined): string => {
    const trimmed = value?.trim();
    if (!trimmed) {
        return '';
    }
    return trimmed.replace(/\/+$/, '');
};

export const getApiBaseUrl = (): string => normalizeApiBaseUrl(import.meta.env.VITE_API_BASE_URL);

export const resolveApiUrl = (path: string): string => {
    const apiBaseUrl = getApiBaseUrl();
    if (!apiBaseUrl) {
        return path;
    }
    return new URL(path, `${apiBaseUrl}/`).toString();
};

export const API_URLS = {
    AUTH: {
        CONFIG: `${API_PREFIX}/auth/config`,
        LOGIN: `${API_PREFIX}/auth/login`,
        REGISTER: `${API_PREFIX}/auth/register`,
        REFRESH_TOKEN: `${API_PREFIX}/auth/refresh`,
        SMS_SEND: `${API_PREFIX}/auth/sms/send`,
        SMS_LOGIN: `${API_PREFIX}/auth/sms/login`,
        GOOGLE_URL: `${API_PREFIX}/auth/google/url`,
        GOOGLE_CALLBACK: `${API_PREFIX}/auth/google/callback`,
    },
    USER: {
        PROFILE: `${API_PREFIX}/users/profile`,
        LIST: `${API_PREFIX}/users/list`,
        ME: `${API_PREFIX}/users/me`,
        CSV_UPLOAD: `${API_PREFIX}/users/csv_upload`,
        QUERY: `${API_PREFIX}/users`,
        UPDATE: (id: string | number) => `${API_PREFIX}/users/${id}`,
    },
    CHAT: {
        QUERY: `${API_PREFIX}/chat/query_sent`,
        QUERY_STREAM: `${API_PREFIX}/chat/query_stream`,
        SESSIONS: `${API_PREFIX}/chat/sessions`,
        SESSION_DETAIL: (id: string) => `${API_PREFIX}/chat/sessions/${id}`,
        REQUEST_RESOLVE: `${API_PREFIX}/chat/requests/resolve`,
        REQUEST_STATUS: (id: string) => `${API_PREFIX}/chat/requests/${id}`,
        REQUEST_RETRY: (id: string) => `${API_PREFIX}/chat/requests/${id}/retry`,
    },
    TELEMETRY: {
        ERRORS: `${API_PREFIX}/telemetry/errors`,
        METRICS: `${API_PREFIX}/telemetry/metrics`,
    },
    KNOWLEDGE: {
        DEFAULT: `${API_PREFIX}/knowledge/default`,
        DEFAULT_UPLOAD: `${API_PREFIX}/knowledge/default/upload`,
        DEFAULT_FILES: `${API_PREFIX}/knowledge/default/files`,
        DELETE_FILE: (id: string) => `${API_PREFIX}/knowledge/files/${id}`,
        TASK_STATUS: (id: string) => `${API_PREFIX}/knowledge/tasks/${id}`,
    },
    CREDITS: {
        ME: `${API_PREFIX}/credits/me`,
        CHECKIN: `${API_PREFIX}/credits/checkin`,
        TRANSACTIONS: `${API_PREFIX}/credits/transactions`,
    },
    REPO_ANALYSIS: {
        README_CHECK: `${API_PREFIX}/repo-analysis/readme-check`,
        RUN: (id: string) => `${API_PREFIX}/repo-analysis/runs/${id}`,
    },
} as const;
