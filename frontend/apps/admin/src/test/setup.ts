import '@testing-library/jest-dom/vitest';
import { act, cleanup } from '@testing-library/react';
import { afterEach, beforeAll, vi } from 'vitest';

import { useAuthStore } from '../stores/auth-store';
import { setupServerLifecycle } from './msw/server';
import { resetFactoryCounters } from './msw/factories';
import { resetCreditMocks } from './msw/handlers/credits';
import appI18n from '../lib/i18n';
import { initReactI18next } from 'react-i18next';
import mockZhCN from '../assets/locales/zh-CN.json';

setupServerLifecycle();

Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
    })),
});

class ResizeObserverMock {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
}
window.ResizeObserver = ResizeObserverMock;
globalThis.ResizeObserver = ResizeObserverMock;


beforeAll(async () => {
    if (!appI18n.isInitialized) {
        await appI18n.use(initReactI18next).init({
            lng: 'zh-CN',
            fallbackLng: 'zh-CN',
            resources: {
                'zh-CN': {
                    translation: mockZhCN,
                },
            },
            interpolation: {
                escapeValue: false,
            },
        });
    }
});

afterEach(async () => {
    if (appI18n.isInitialized) {
        if (!appI18n.hasResourceBundle('zh-CN', 'translation')) {
            appI18n.addResourceBundle('zh-CN', 'translation', mockZhCN, true, true);
        }
        if (appI18n.hasResourceBundle('en-US', 'translation')) {
            appI18n.removeResourceBundle('en-US', 'translation');
        }
        await act(async () => {
            await appI18n.changeLanguage('zh-CN');
        });
    }
    cleanup();
    localStorage.clear();
    sessionStorage.clear();
    useAuthStore.getState().resetAll();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.history.pushState({}, '', '/');
    resetFactoryCounters();
    resetCreditMocks();
});
