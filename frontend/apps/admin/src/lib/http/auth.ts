export const AUTH_TOKEN_STORAGE_KEY = 'token';
export const AUTH_UNAUTHORIZED_EVENT = 'app:http:unauthorized';

export const getAccessToken = (): string | null => {
    return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
};

export const setAccessToken = (token: string): void => {
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
};

export const clearAccessToken = (): void => {
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
};

export const notifyUnauthorized = (): void => {
    if (typeof window !== 'undefined') {
        window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
    }
};
