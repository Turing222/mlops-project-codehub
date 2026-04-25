import { createContext } from 'react';

import type { User } from '../types/user';

export interface AuthContextType {
    user: User | null;
    token: string | null;
    isLoading: boolean;
    login: (token: string) => Promise<void>;
    logout: () => void;
    isAuthenticated: boolean;
    showAuthModal: boolean;
    setShowAuthModal: (show: boolean) => void;
    refreshUser: () => Promise<void>;
    authTab: 'login' | 'register';
    setAuthTab: (tab: 'login' | 'register') => void;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);
