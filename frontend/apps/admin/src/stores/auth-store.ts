import { create } from 'zustand';
import { persist } from 'zustand/middleware';

type AuthStoreState = {
    token: string | null;
    showAuthModal: boolean;
};

type AuthStoreActions = {
    setToken: (token: string | null) => void;
    setShowAuthModal: (show: boolean) => void;
    clearAuth: () => void;
    resetAll: () => void;
};

const initialState: AuthStoreState = {
    token: null,
    showAuthModal: false,
};

export const useAuthStore = create<AuthStoreState & AuthStoreActions>()(
    persist(
        (set) => ({
            ...initialState,
            setToken: (token) => set({ token }),
            setShowAuthModal: (showAuthModal) => set({ showAuthModal }),
            clearAuth: () => set({ token: null }),
            resetAll: () => set(initialState),
        }),
        {
            // SECURITY NOTE: JWT is persisted to localStorage, making it accessible
            // to XSS. Long-term fix: migrate to HttpOnly cookie set by the backend.
            // Current mitigation: short token expiry, CSP headers, no eval/innerHTML.
            name: 'auth-storage',
            partialize: (state) => ({
                token: state.token,
            }),
        },
    ),
);
