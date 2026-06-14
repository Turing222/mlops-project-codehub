import { act, render } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { useThemeStore } from '../stores/theme-store';
import { detectBrowserLanguage, loadLocaleResources, initI18n, changeAppLanguage } from '../lib/i18n';
import i18n from '../lib/i18n';
import App from '../App';

type TestLocaleResource = {
    sidebar: {
        new_chat: string;
    };
};

vi.mock('../context/useAuth', () => ({
    useAuth: () => ({
        isAuthenticated: false,
        isLoading: false,
        user: null,
        setShowAuthModal: vi.fn(),
    }),
}));

vi.mock('../pages/Chat', () => ({
    default: () => <div>chat-page</div>,
}));

vi.mock('../pages/Admin', () => ({
    default: () => <div>admin-dashboard</div>,
}));

vi.mock('../context/AuthContext', () => ({
    AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

describe('Theme System', () => {
    beforeEach(() => {
        act(() => {
            useThemeStore.getState().resetAll();
        });
    });

    it('should initialize with default states', () => {
        const state = useThemeStore.getState();
        expect(state.theme).toBe('light');
        expect(state.brandColor).toBe('#1677ff');
    });

    it('should update theme correctly', () => {
        act(() => {
            useThemeStore.getState().setTheme('dark');
        });
        expect(useThemeStore.getState().theme).toBe('dark');

        act(() => {
            useThemeStore.getState().setTheme('light');
        });
        expect(useThemeStore.getState().theme).toBe('light');
    });

    it('should update brandColor correctly', () => {
        act(() => {
            useThemeStore.getState().setBrandColor('#722ed1'); // Royal Purple
        });
        expect(useThemeStore.getState().brandColor).toBe('#722ed1');
    });

    it('should reset all states to default', () => {
        act(() => {
            useThemeStore.getState().setTheme('dark');
            useThemeStore.getState().setBrandColor('#13c2c2'); // Teal
        });

        expect(useThemeStore.getState().theme).toBe('dark');
        expect(useThemeStore.getState().brandColor).toBe('#13c2c2');

        act(() => {
            useThemeStore.getState().resetAll();
        });

        expect(useThemeStore.getState().theme).toBe('light');
        expect(useThemeStore.getState().brandColor).toBe('#1677ff');
    });
});

describe('Internationalization (i18n) System', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
        localStorage.clear();
    });

    describe('detectBrowserLanguage', () => {
        it('should return zh-CN if navigator language starts with zh', () => {
            vi.stubGlobal('navigator', {
                language: 'zh-TW',
            });
            expect(detectBrowserLanguage()).toBe('zh-CN');

            vi.stubGlobal('navigator', {
                language: 'zh-CN',
            });
            expect(detectBrowserLanguage()).toBe('zh-CN');
        });

        it('should return en-US if navigator language starts with en', () => {
            vi.stubGlobal('navigator', {
                language: 'en-GB',
            });
            expect(detectBrowserLanguage()).toBe('en-US');

            vi.stubGlobal('navigator', {
                language: 'en-US',
            });
            expect(detectBrowserLanguage()).toBe('en-US');
        });

        it('should return zh-CN (fallback) if navigator language is unsupported', () => {
            vi.stubGlobal('navigator', {
                language: 'ja-JP',
            });
            expect(detectBrowserLanguage()).toBe('zh-CN');

            vi.stubGlobal('navigator', {
                language: 'fr-FR',
            });
            expect(detectBrowserLanguage()).toBe('zh-CN');
        });
    });

    describe('loadLocaleResources', () => {
        it('should load zh-CN locale bundle successfully', async () => {
            const resource = await loadLocaleResources('zh-CN') as TestLocaleResource;
            expect(resource).toBeDefined();
            expect(resource.sidebar).toBeDefined();
            expect(resource.sidebar.new_chat).toBe('新对话');
        });

        it('should load en-US locale bundle successfully', async () => {
            const resource = await loadLocaleResources('en-US') as TestLocaleResource;
            expect(resource).toBeDefined();
            expect(resource.sidebar).toBeDefined();
            expect(resource.sidebar.new_chat).toBe('New Chat');
        });

        it('should safely fallback to zh-CN when an invalid or unsupported locale is requested', async () => {
            // Test traversal attempt
            const resourceTraversal = await loadLocaleResources('../../../evil') as TestLocaleResource;
            expect(resourceTraversal).toBeDefined();
            expect(resourceTraversal.sidebar.new_chat).toBe('新对话');

            // Test unsupported language tag
            const resourceUnsupported = await loadLocaleResources('fr-FR') as TestLocaleResource;
            expect(resourceUnsupported).toBeDefined();
            expect(resourceUnsupported.sidebar.new_chat).toBe('新对话');
        });
    });

    describe('initI18n', () => {
        it('should initialize i18next instance and register translation', async () => {
            localStorage.setItem('dewflow-lng', 'en-US');
            
            // Trigger setup
            await initI18n();
            
            // Check current resolved language and loaded translation
            expect(i18n.language).toBe('en-US');
            expect(i18n.t('sidebar.new_chat')).toBe('New Chat');
        });

        it('should change and dynamically load locale on demand', async () => {
            await initI18n();
            if (i18n.hasResourceBundle('en-US', 'translation')) {
                i18n.removeResourceBundle('en-US', 'translation');
            }
            
            // Switch language to en-US
            await act(async () => {
                await changeAppLanguage('en-US');
            });
            
            expect(i18n.language).toBe('en-US');
            expect(i18n.hasResourceBundle('en-US', 'translation')).toBe(true);
            expect(i18n.t('sidebar.new_chat')).toBe('New Chat');
        });
    });
});

describe('Theme Store to Document.documentElement Linkage', () => {
    it('should synchronize theme and brand colors to document.documentElement', () => {
        act(() => {
            useThemeStore.getState().setTheme('dark');
            useThemeStore.getState().setBrandColor('#0d9488');
        });

        render(<App />);

        expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
        expect(document.documentElement.style.getPropertyValue('--color-primary')).toBe('#0d9488');
        expect(document.documentElement.style.getPropertyValue('--color-primary-hover')).toBe('#0d9488cc');
        expect(document.documentElement.style.getPropertyValue('--color-primary-shadow')).toBe('#0d948826');
        expect(document.documentElement.style.getPropertyValue('--color-primary-gradient-end')).toBe('#0284c7');
    });
});
