import React, { useEffect, useState, type ReactNode } from 'react';

import { getUserProfileAPI } from '../api/auth';
import {
    AUTH_UNAUTHORIZED_EVENT,
    clearAccessToken,
    getAccessToken,
    setAccessToken,
} from '../lib/http/auth';
import type { User } from '../types/user';
import { AuthContext } from './auth-context';

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [token, setToken] = useState<string | null>(getAccessToken());
    const [isLoading, setIsLoading] = useState<boolean>(true);
    const [showAuthModal, setShowAuthModal] = useState(false);
    const [authTab, setAuthTab] = useState<'login' | 'register'>('login');

    const refreshUser = async () => {
        if (token) {
            try {
                const userData = await getUserProfileAPI();
                setUser(userData);
            } catch (error) {
                console.error('Failed to refresh user profile', error);
            }
        }
    };

    useEffect(() => {
        const initAuth = async () => {
            if (token) {
                try {
                    const userData = await getUserProfileAPI();
                    setUser(userData);
                } catch {
                    // Token 过期或无效，清除但不跳转（匿名也可用）
                    clearAccessToken();
                    setToken(null);
                    setUser(null);
                }
            }
            setIsLoading(false);
        };
        initAuth();
    }, [token]);

    useEffect(() => {
        const handleUnauthorized = () => {
            setToken(null);
            setUser(null);
        };

        window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
        return () => {
            window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
        };
    }, []);

    const login = async (newToken: string) => {
        setAccessToken(newToken);
        setToken(newToken);
        try {
            setIsLoading(true);
            const userData = await getUserProfileAPI();
            setUser(userData);
            setShowAuthModal(false); // 登录成功自动关闭弹窗
        } catch (error) {
            console.error('Failed to get user profile', error);
            logout();
            throw error;
        } finally {
            setIsLoading(false);
        }
    };

    const logout = () => {
        clearAccessToken();
        setToken(null);
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{
            user,
            token,
            login,
            logout,
            isLoading,
            isAuthenticated: !!user,
            showAuthModal,
            setShowAuthModal,
            refreshUser,
            authTab,
            setAuthTab,
        }}>
            {children}
        </AuthContext.Provider>
    );
};
