import { create } from 'zustand';
import { persist } from 'zustand/middleware';

type ThemeStoreState = {
    theme: 'light' | 'dark';
    brandColor: string;
};

type ThemeStoreActions = {
    setTheme: (theme: 'light' | 'dark') => void;
    setBrandColor: (color: string) => void;
    resetAll: () => void;
};

// 首次访问跟随系统偏好;用户显式选择过(persist 有值)则以持久化状态为准。
const prefersDark = () =>
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches;

const initialState: ThemeStoreState = {
    theme: prefersDark() ? 'dark' : 'light',
    brandColor: '#1677ff', // 默认经典蓝 (#1677ff)
};

export const useThemeStore = create<ThemeStoreState & ThemeStoreActions>()(
    persist(
        (set) => ({
            ...initialState,
            setTheme: (theme) => set({ theme }),
            setBrandColor: (brandColor) => set({ brandColor }),
            resetAll: () => set(initialState),
        }),
        {
            name: 'dewflow-theme-settings',
            partialize: (state) => ({ theme: state.theme, brandColor: state.brandColor }),
        },
    ),
);
