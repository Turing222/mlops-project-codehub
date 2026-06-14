import { describe, expect, it } from 'vitest';

import { useAuthStore } from './auth-store';

describe('auth-store', () => {
    it('starts with null token and default UI state', () => {
        useAuthStore.getState().resetAll();
        const state = useAuthStore.getState();
        expect(state.token).toBeNull();
        expect(state.showAuthModal).toBe(false);
    });

    it('setToken updates the token', () => {
        useAuthStore.getState().resetAll();
        useAuthStore.getState().setToken('abc123');
        expect(useAuthStore.getState().token).toBe('abc123');
    });

    it('clearAuth zeros the token but keeps UI state', () => {
        useAuthStore.getState().resetAll();
        useAuthStore.getState().setToken('abc123');
        useAuthStore.getState().setShowAuthModal(true);
        useAuthStore.getState().clearAuth();
        expect(useAuthStore.getState().token).toBeNull();
        expect(useAuthStore.getState().showAuthModal).toBe(true);
    });

    it('resetAll returns to initial state', () => {
        useAuthStore.getState().setToken('abc123');
        useAuthStore.getState().setShowAuthModal(true);
        useAuthStore.getState().resetAll();
        const state = useAuthStore.getState();
        expect(state.token).toBeNull();
        expect(state.showAuthModal).toBe(false);
    });

    it('partialize only persists token', () => {
        useAuthStore.getState().resetAll();
        useAuthStore.getState().setToken('persisted-token');
        useAuthStore.getState().setShowAuthModal(true);

        const raw = localStorage.getItem('auth-storage');
        const persisted = raw ? JSON.parse(raw) : {};
        expect(persisted.state).toEqual({ token: 'persisted-token' });
    });
});
