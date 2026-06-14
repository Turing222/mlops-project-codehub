import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { API_URLS, resolveApiUrl } from '../../api/urls';

vi.mock('web-vitals', () => ({
    onCLS: vi.fn(),
    onFCP: vi.fn(),
    onINP: vi.fn(),
    onLCP: vi.fn(),
    onTTFB: vi.fn(),
}));

import { onCLS, onFCP, onINP, onLCP, onTTFB, type Metric } from 'web-vitals';
import { registerWebVitals, resetWebVitalsForTests } from './web-vitals';

// web-vitals 把每个 onXXX 回调收窄为 LCPMetric/CLSMetric/...；测试里统一按通用 Metric 驱动
// （运行期 reportWebVital 本就接收任意 Metric），故对取出的回调做一次显式拓宽。
type MetricReporter = (metric: Metric) => void;

const makeMetric = (overrides: Partial<Metric> = {}): Metric =>
    ({
        name: 'LCP',
        value: 2300.4,
        rating: 'good',
        delta: 2300.4,
        id: 'v5-lcp-123',
        navigationType: 'navigate',
        entries: [],
        ...overrides,
    }) as Metric;

describe('web vitals reporter', () => {
    beforeEach(() => {
        resetWebVitalsForTests();
        vi.clearAllMocks();
    });

    afterEach(() => {
        vi.unstubAllEnvs();
        vi.unstubAllGlobals();
        resetWebVitalsForTests();
    });

    it('registers all five Web Vitals collectors exactly once', () => {
        vi.stubGlobal('navigator', { sendBeacon: vi.fn().mockReturnValue(true) });

        registerWebVitals();

        expect(onLCP).toHaveBeenCalledTimes(1);
        expect(onINP).toHaveBeenCalledTimes(1);
        expect(onCLS).toHaveBeenCalledTimes(1);
        expect(onFCP).toHaveBeenCalledTimes(1);
        expect(onTTFB).toHaveBeenCalledTimes(1);
    });

    it('is idempotent: repeated registration does not double-register', () => {
        vi.stubGlobal('navigator', { sendBeacon: vi.fn().mockReturnValue(true) });

        registerWebVitals();
        registerWebVitals();

        expect(onLCP).toHaveBeenCalledTimes(1);
        expect(onCLS).toHaveBeenCalledTimes(1);
    });

    it('posts a metric to the metrics channel via sendBeacon, not the error channel', () => {
        const sendBeacon = vi.fn().mockReturnValue(true);
        const fetchMock = vi.fn();
        vi.stubGlobal('navigator', { sendBeacon });
        vi.stubGlobal('fetch', fetchMock);

        registerWebVitals();
        const report = vi.mocked(onLCP).mock.calls[0][0] as unknown as MetricReporter;
        report(makeMetric());

        expect(sendBeacon).toHaveBeenCalledTimes(1);
        expect(sendBeacon).toHaveBeenCalledWith(
            resolveApiUrl(API_URLS.TELEMETRY.METRICS),
            expect.any(Blob),
        );
        expect(sendBeacon).not.toHaveBeenCalledWith(
            resolveApiUrl(API_URLS.TELEMETRY.ERRORS),
            expect.anything(),
        );
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('falls back to fetch keepalive and sends the Web Vitals payload shape', () => {
        const sendBeacon = vi.fn().mockReturnValue(false);
        const fetchMock = vi.fn().mockResolvedValue(undefined);
        vi.stubGlobal('navigator', { sendBeacon });
        vi.stubGlobal('fetch', fetchMock);

        registerWebVitals();
        const report = vi.mocked(onCLS).mock.calls[0][0] as unknown as MetricReporter;
        report(makeMetric({ name: 'CLS', value: 0.05, rating: 'needs-improvement', id: 'v5-cls-9' }));

        expect(fetchMock).toHaveBeenCalledWith(
            resolveApiUrl(API_URLS.TELEMETRY.METRICS),
            expect.objectContaining({ method: 'POST', keepalive: true }),
        );
        const init = fetchMock.mock.calls[0][1] as RequestInit;
        const body = JSON.parse(init.body as string);
        expect(body).toMatchObject({
            name: 'CLS',
            value: 0.05,
            rating: 'needs-improvement',
            id: 'v5-cls-9',
            navigationType: 'navigate',
        });
        // 携带路由维度，便于后端按页面聚合。
        expect(typeof body.url).toBe('string');
        expect(typeof body.page).toBe('string');
        // 绝不混入 error telemetry 的 severity 语义。
        expect(body.severity).toBeUndefined();
    });

    it('truncates url and page to the backend bounds so long locations are not 422-dropped', () => {
        const sendBeacon = vi.fn().mockReturnValue(false);
        const fetchMock = vi.fn().mockResolvedValue(undefined);
        vi.stubGlobal('navigator', { sendBeacon });
        vi.stubGlobal('fetch', fetchMock);
        vi.stubGlobal('location', {
            href: `https://admin.example.com/${'a'.repeat(3000)}`,
            pathname: `/${'b'.repeat(800)}`,
        });

        registerWebVitals();
        const report = vi.mocked(onTTFB).mock.calls[0][0] as unknown as MetricReporter;
        report(makeMetric({ name: 'TTFB', value: 120, rating: 'good', id: 'v5-ttfb-9' }));

        const init = fetchMock.mock.calls[0][1] as RequestInit;
        const body = JSON.parse(init.body as string);
        // 后端 url ≤ 2048、page ≤ 512；截断后正好贴边而非越界。
        expect(body.url).toHaveLength(2048);
        expect(body.page).toHaveLength(512);
    });

    it('uses an absolute metrics URL when VITE_API_BASE_URL is configured', () => {
        const sendBeacon = vi.fn().mockReturnValue(true);
        vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com');
        vi.stubGlobal('navigator', { sendBeacon });

        registerWebVitals();
        const report = vi.mocked(onINP).mock.calls[0][0] as unknown as MetricReporter;
        report(makeMetric({ name: 'INP', value: 180, rating: 'good', id: 'v5-inp-3' }));

        expect(sendBeacon).toHaveBeenCalledWith(
            'https://api.example.com/api/v1/telemetry/metrics',
            expect.any(Blob),
        );
    });
});
