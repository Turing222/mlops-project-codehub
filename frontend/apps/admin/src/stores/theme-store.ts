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

const initialState: ThemeStoreState = {
    theme: 'light',
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
