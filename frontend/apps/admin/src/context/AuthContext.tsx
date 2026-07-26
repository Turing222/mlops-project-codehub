import React, { useEffect, useCallback, useMemo, useRef, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import {
    AUTH_UNAUTHORIZED_EVENT,
    type UnauthorizedEventDetail,
} from '../lib/http/auth';
import { meQueryOptions, useMeQuery } from '../query/hooks/auth';
import { useAuthStore } from '../stores/auth-store';
import { AuthContext } from './auth-context';

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const token = useAuthStore((s) => s.token);
    const showAuthModal = useAuthStore((s) => s.showAuthModal);
    const setToken = useAuthStore((s) => s.setToken);
    const setShowAuthModal = useAuthStore((s) => s.setShowAuthModal);
    const clearAuth = useAuthStore((s) => s.clearAuth);

    // isLoadingError = first-fetch failure only; background refetch errors must not log out.
    const { data: meUser, isLoading, isLoadingError, refetch } = useMeQuery();
    const queryClient = useQueryClient();

    // Serializes concurrent cancel/clear so overlapping 401 + logout cannot race.
    const terminateChainRef = useRef<Promise<void>>(Promise.resolve());

    const terminateIdentitySession = useCallback(async (options?: { force?: boolean }) => {
        const currentToken = useAuthStore.getState().token;
        if (!options?.force && !currentToken) {
            return;
        }

        // Synchronous anonymous entry before any async scheduling (logout contract).
        clearAuth();

        const run = async () => {
            await queryClient.cancelQueries();
            queryClient.clear();
        };

        const next = terminateChainRef.current.then(run, run);
        terminateChainRef.current = next.then(
            () => undefined,
            () => undefined,
        );
        await next;
    }, [clearAuth, queryClient]);

    useEffect(() => {
        const handleUnauthorizedEvent = (event: Event) => {
            const detail = (event as CustomEvent<UnauthorizedEventDetail>).detail;
            const currentToken = useAuthStore.getState().token;

            // Legacy plain Event (no detail): act on current identity only.
            if (detail === undefined) {
                void terminateIdentitySession();
                return;
            }

            // Explicit request identity: only tear down when it still matches.
            if (detail.token !== currentToken) {
                return;
            }

            void terminateIdentitySession();
        };

        window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorizedEvent);
        return () => {
            window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorizedEvent);
        };
    }, [terminateIdentitySession]);

    // Persisted-token *initial* bootstrap failures (network/5xx/schema) tear down identity.
    // Do not use plain isError: a background refetch 500 after success is isRefetchError.
    // 401/403 continue through the unauthorized event path.
    useEffect(() => {
        if (!token || !isLoadingError || meUser) {
            return;
        }
        void terminateIdentitySession({ force: true });
    }, [token, isLoadingError, meUser, terminateIdentitySession]);

    const login = useCallback(async (newToken: string) => {
        const currentToken = useAuthStore.getState().token;
        // Identity-replace transaction: drop prior identity before bootstrapping the new one.
        if (currentToken || meUser) {
            await terminateIdentitySession({ force: true });
        }

        setToken(newToken);
        try {
            await queryClient.fetchQuery(meQueryOptions());
            setShowAuthModal(false);
        } catch (error) {
            await terminateIdentitySession({ force: true });
            throw error;
        }
    }, [meUser, setToken, setShowAuthModal, queryClient, terminateIdentitySession]);

    // Public shape stays sync void; force-clear even when token already empty.
    // clearAuth runs synchronously inside terminateIdentitySession before async chain.
    const logout = useCallback(() => {
        void terminateIdentitySession({ force: true });
    }, [terminateIdentitySession]);

    const refreshUser = useCallback(async () => {
        await refetch();
    }, [refetch]);

    // Token empty => immediate anonymous exposure; do not wait for async query clear.
    const user = token ? (meUser ?? null) : null;
    const isAuthenticated = !!token && !!user;

    const contextValue = useMemo(() => ({
        user,
        token,
        login,
        logout,
        isLoading: isLoading && !!token,
        isAuthenticated,
        showAuthModal,
        setShowAuthModal,
        refreshUser,
    }), [user, token, login, logout, isLoading, isAuthenticated, showAuthModal, setShowAuthModal, refreshUser]);

    return (
        <AuthContext.Provider value={contextValue}>
            {children}
        </AuthContext.Provider>
    );
};
