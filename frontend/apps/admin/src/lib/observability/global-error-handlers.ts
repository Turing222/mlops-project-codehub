import { normalizeErrorMessage, reportFrontendErrorEvent } from '../http/telemetry';

// 用 window 级标记而非模块级变量：Vite HMR 重新执行本模块时模块级变量会被重置回
// 初始值，但已注册的 window listener 不会随旧模块卸载而移除——靠 window 上的标记
// 跨模块实例持久，才能真正保证 dev/HMR 下不重复注册、不重复上报。
const REGISTERED_FLAG = '__dewflowGlobalErrorHandlersRegistered';

const isRegistered = (): boolean =>
    typeof window !== 'undefined' &&
    Boolean((window as unknown as Record<string, boolean>)[REGISTERED_FLAG]);

const markRegistered = (value: boolean): void => {
    if (typeof window === 'undefined') {
        return;
    }
    (window as unknown as Record<string, boolean>)[REGISTERED_FLAG] = value;
};

const currentUrl = (): string | undefined =>
    typeof window !== 'undefined' ? window.location.href : undefined;

/**
 * 注册一次性的全局浏览器错误观测：
 * - `error`：未捕获的全局 JS 错误（含 filename/line/column）。
 * - `unhandledrejection`：未处理的 promise rejection。
 *
 * 幂等：通过 window 级标记，确保即使模块被重复加载（StrictMode/HMR）也只注册一次。
 */
export const registerGlobalErrorHandlers = (): void => {
    if (typeof window === 'undefined' || isRegistered()) {
        return;
    }
    markRegistered(true);

    window.addEventListener('error', (event: ErrorEvent) => {
        reportFrontendErrorEvent({
            eventType: 'global_error',
            source: 'window_error',
            message: normalizeErrorMessage(event.error ?? event.message),
            url: currentUrl(),
            metadata: {
                filename: event.filename || '',
                line: event.lineno ?? 0,
                column: event.colno ?? 0,
            },
        });
    });

    window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
        reportFrontendErrorEvent({
            eventType: 'unhandled_rejection',
            source: 'window_unhandledrejection',
            message: normalizeErrorMessage(event.reason),
            url: currentUrl(),
        });
    });
};

/**
 * Bootstrap 阶段 i18n 初始化失败上报（归入 global_error，单独 source 便于检索）。
 */
export const reportI18nInitFailure = (error: unknown): void => {
    reportFrontendErrorEvent({
        eventType: 'global_error',
        source: 'i18n_init',
        message: normalizeErrorMessage(error),
        url: currentUrl(),
    });
};

export const resetGlobalErrorHandlersForTests = (): void => {
    markRegistered(false);
};
