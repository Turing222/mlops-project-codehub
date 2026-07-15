import { useAuthStore } from '../../stores/auth-store';

export const AUTH_UNAUTHORIZED_EVENT = 'app:http:unauthorized';

export type UnauthorizedEventDetail = {
    /** Token that was bound to the failing request; used to avoid killing a newer identity. */
    token: string | null;
};

export const getAccessToken = (): string | null => {
    return useAuthStore.getState().token;
};

export const setAccessToken = (token: string): void => {
    useAuthStore.getState().setToken(token);
};

export const clearAccessToken = (): void => {
    useAuthStore.getState().clearAuth();
};

/**
 * Dispatch unauthorized for the identity that made the failing request.
 * Prefer passing the request-time token so a delayed A 401 cannot log out B.
 */
export const notifyUnauthorized = (requestToken?: string | null): void => {
    if (typeof window === 'undefined') {
        return;
    }
    const token = requestToken !== undefined ? requestToken : getAccessToken();
    const detail: UnauthorizedEventDetail = { token };
    window.dispatchEvent(
        new CustomEvent<UnauthorizedEventDetail>(AUTH_UNAUTHORIZED_EVENT, { detail }),
    );
};

export const handleUnauthorized = (requestToken?: string | null): void => {
    notifyUnauthorized(requestToken);
};
