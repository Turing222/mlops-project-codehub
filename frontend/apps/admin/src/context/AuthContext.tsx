import React, { useEffect, useCallback, useMemo, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { AUTH_UNAUTHORIZED_EVENT } from '../lib/http/auth';
import { authKeys } from '../query/keys/auth';
import { useMeQuery } from '../query/hooks/auth';
import { useAuthStore } from '../stores/auth-store';
import { AuthContext } from './auth-context';

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const token = useAuthStore((s) => s.token);
    const showAuthModal = useAuthStore((s) => s.showAuthModal);
    const setToken = useAuthStore((s) => s.setToken);
    const setShowAuthModal = useAuthStore((s) => s.setShowAuthModal);
    const clearAuth = useAuthStore((s) => s.clearAuth);

    const { data: user, isLoading, refetch } = useMeQuery();
    const queryClient = useQueryClient();

    useEffect(() => {
        const handleUnauthorizedEvent = () => {
            clearAuth();
            queryClient.removeQueries({ queryKey: authKeys.all() });
        };

        window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorizedEvent);
        return () => {
            window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorizedEvent);
        };
    }, [clearAuth, queryClient]);

    const login = useCallback(async (newToken: string) => {
        setToken(newToken);
        const result = await refetch();
        if (result.error) {
            clearAuth();
            throw result.error;
        }
        setShowAuthModal(false);
    }, [setToken, refetch, clearAuth, setShowAuthModal]);

    const logout = useCallback(() => {
        clearAuth();
        queryClient.clear();
    }, [clearAuth, queryClient]);

    const refreshUser = useCallback(async () => {
        await refetch();
    }, [refetch]);

    const contextValue = useMemo(() => ({
        user: user ?? null,
        token,
        login,
        logout,
        isLoading: isLoading && !!token,
        isAuthenticated: !!user,
        showAuthModal,
        setShowAuthModal,
        refreshUser,
    }), [user, token, login, logout, isLoading, showAuthModal, setShowAuthModal, refreshUser]);

    return (
        <AuthContext.Provider value={contextValue}>
            {children}
        </AuthContext.Provider>
    );
};
