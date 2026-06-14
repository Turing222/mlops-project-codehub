import i18n from 'i18next';
import type { ResourceLanguage } from 'i18next';
import { initReactI18next } from 'react-i18next';

// 默认语言与回退语言
const SUPPORTED_LANGS = ['zh-CN', 'en-US'];
const FALLBACK_LANG = 'zh-CN';

// 检测浏览器默认语言
export const detectBrowserLanguage = (): string => {
    const browserNavigator = navigator as Navigator & { userLanguage?: string };
    const browserLang = navigator.language || browserNavigator.userLanguage || '';
    if (browserLang.startsWith('zh')) {
        return 'zh-CN';
    }
    if (browserLang.startsWith('en')) {
        return 'en-US';
    }
    return FALLBACK_LANG;
};

// 动态加载对应语言包的辅助函数
export const loadLocaleResources = async (lng: string): Promise<ResourceLanguage> => {
    if (!SUPPORTED_LANGS.includes(lng)) {
        lng = FALLBACK_LANG;
    }

    try {
        switch (lng) {
            case 'zh-CN':
                return (await import('../assets/locales/zh-CN.json')).default;
            case 'en-US':
                return (await import('../assets/locales/en-US.json')).default;
            default:
                return (await import('../assets/locales/zh-CN.json')).default;
        }
    } catch (error) {
        console.error(`Failed to load translation bundle for dynamic locale: ${lng}`, error);
        return {};
    }
};

export const ensureLocaleResources = async (lng: string): Promise<string> => {
    const supportedLng = SUPPORTED_LANGS.includes(lng) ? lng : FALLBACK_LANG;

    if (!i18n.hasResourceBundle(supportedLng, 'translation')) {
        const resources = await loadLocaleResources(supportedLng);
        i18n.addResourceBundle(supportedLng, 'translation', resources, true, true);
    }

    return supportedLng;
};

export const changeAppLanguage = async (lng: string): Promise<void> => {
    const supportedLng = await ensureLocaleResources(lng);
    await i18n.changeLanguage(supportedLng);
};

// 自定义浏览器语言检测及缓存插件
const customLanguageDetector = {
    type: 'languageDetector' as const,
    async: false,
    detect: () => {
        const stored = localStorage.getItem('dewflow-lng');
        if (stored && SUPPORTED_LANGS.includes(stored)) {
            return stored;
        }
        return detectBrowserLanguage();
    },
    cacheUserLanguage: (lng: string) => {
        if (SUPPORTED_LANGS.includes(lng)) {
            localStorage.setItem('dewflow-lng', lng);
        }
    },
};

// 初始化 i18n 系统的入口函数
export const initI18n = async () => {
    const initialLng = customLanguageDetector.detect();
    const initialResources = await loadLocaleResources(initialLng);

    await i18n
        .use(customLanguageDetector)
        .use(initReactI18next)
        .init({
            lng: initialLng,
            fallbackLng: FALLBACK_LANG,
            interpolation: {
                escapeValue: false, // React already escapes values securely to prevent XSS
            },
            resources: {
                [initialLng]: {
                    translation: initialResources,
                },
            },
        });
};

export default i18n;
