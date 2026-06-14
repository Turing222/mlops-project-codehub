import { onCLS, onFCP, onINP, onLCP, onTTFB, type Metric } from 'web-vitals';

import { API_URLS, resolveApiUrl } from '../../api/urls';
import { beaconPost } from '../http/beacon';

// 与 global-error-handlers 同源策略：用 window 级标记而非模块级变量，确保 StrictMode/HMR
// 下本模块被重复执行也只注册一次 web-vitals 回调（重复注册会让同一指标被多次上报）。
const REGISTERED_FLAG = '__dewflowWebVitalsRegistered';

const isRegistered = (): boolean =>
    typeof window !== 'undefined' &&
    Boolean((window as unknown as Record<string, boolean>)[REGISTERED_FLAG]);

const markRegistered = (value: boolean): void => {
    if (typeof window === 'undefined') {
        return;
    }
    (window as unknown as Record<string, boolean>)[REGISTERED_FLAG] = value;
};

// 与后端 metrics schema（telemetry_api.py 的 FrontendMetricTelemetry）上限对齐，
// 避免长 URL / 长 path 让合法指标被后端判 422 静默丢弃。
const MAX_URL_LENGTH = 2048;
const MAX_PAGE_LENGTH = 512;

const truncate = (value: string, max: number): string =>
    value.length > max ? value.slice(0, max) : value;

// 走独立 metrics 通道；与 error telemetry 语义分离，绝不复用 reportFrontendErrorEvent。
const reportWebVital = (metric: Metric): void => {
    const hasWindow = typeof window !== 'undefined';
    beaconPost(resolveApiUrl(API_URLS.TELEMETRY.METRICS), {
        name: metric.name,
        value: metric.value,
        rating: metric.rating,
        id: metric.id,
        navigationType: metric.navigationType,
        url: hasWindow ? truncate(window.location.href, MAX_URL_LENGTH) : undefined,
        page: hasWindow ? truncate(window.location.pathname, MAX_PAGE_LENGTH) : undefined,
    });
};

/**
 * 注册 Web Vitals 采集（LCP / INP / CLS / FCP / TTFB）。
 *
 * 每条指标在其生命周期内取得终值时上报一次：web-vitals 默认 `reportAllChanges=false`，
 * SPA 下随页面隐藏（visibilitychange/pagehide）汇报，避免单页应用漏报或重复上报。
 *
 * 幂等：通过 window 级标记，确保模块被重复加载（StrictMode/HMR）也只注册一次。
 */
export const registerWebVitals = (): void => {
    if (typeof window === 'undefined' || isRegistered()) {
        return;
    }
    markRegistered(true);

    onLCP(reportWebVital);
    onINP(reportWebVital);
    onCLS(reportWebVital);
    onFCP(reportWebVital);
    onTTFB(reportWebVital);
};

export const resetWebVitalsForTests = (): void => {
    markRegistered(false);
};
