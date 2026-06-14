import { describe, expect, it } from 'vitest';

import { buildCsp, renderHeaders, resolveApiOrigin } from './generate-pages-headers.mjs';

const BASE_HEADERS = `/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: SAMEORIGIN
  Referrer-Policy: strict-origin-when-cross-origin

/assets/*
  Cache-Control: public, max-age=31536000, immutable
`;

describe('resolveApiOrigin', () => {
    it('returns null without VITE_API_BASE_URL outside Cloudflare Pages', () => {
        expect(resolveApiOrigin(undefined, { isCloudflarePages: false })).toBeNull();
        expect(resolveApiOrigin('', { isCloudflarePages: false })).toBeNull();
    });

    it('fails fast on Cloudflare Pages when VITE_API_BASE_URL is missing', () => {
        expect(() => resolveApiOrigin(undefined, { isCloudflarePages: true })).toThrow(
            /VITE_API_BASE_URL is required/,
        );
    });

    it('rejects non-https origins on Cloudflare Pages', () => {
        expect(() =>
            resolveApiOrigin('http://api.example.com', { isCloudflarePages: true }),
        ).toThrow(/https origin/);
    });

    it('allows http origins outside Cloudflare Pages for local fallback', () => {
        expect(resolveApiOrigin('http://127.0.0.1:8000', { isCloudflarePages: false })).toBe(
            'http://127.0.0.1:8000',
        );
    });

    it('normalizes the value to its origin', () => {
        expect(
            resolveApiOrigin('https://api.example.com/api/v1', { isCloudflarePages: true }),
        ).toBe('https://api.example.com');
    });
});

describe('buildCsp', () => {
    it('points connect-src and report-uri at the API origin', () => {
        const csp = buildCsp('https://api.example.com');
        expect(csp).toContain("connect-src 'self' https://api.example.com");
        expect(csp).toContain('report-uri https://api.example.com/api/v1/csp/reports');
    });
});

describe('renderHeaders', () => {
    it('inserts the report-only CSP header after Referrer-Policy', () => {
        const headers = renderHeaders(BASE_HEADERS, 'https://api.example.com');
        const lines = headers.split('\n');
        const referrerIndex = lines.findIndex((line) => line.includes('Referrer-Policy'));
        expect(lines[referrerIndex + 1]).toContain('Content-Security-Policy-Report-Only:');
        expect(headers).toContain('report-uri https://api.example.com/api/v1/csp/reports');
    });

    it('keeps the base headers unchanged without an API origin', () => {
        const headers = renderHeaders(BASE_HEADERS, null);
        expect(headers).toBe(BASE_HEADERS);
        expect(headers).not.toContain('Content-Security-Policy-Report-Only');
    });

    it('fails when the Referrer-Policy anchor line is missing', () => {
        expect(() => renderHeaders('/*\n  X-Frame-Options: SAMEORIGIN\n', 'https://api.example.com')).toThrow(
            /must include Content-Security-Policy-Report-Only/,
        );
    });

    it('rejects leftover placeholder tokens', () => {
        const withPlaceholder = BASE_HEADERS.replace(
            'strict-origin-when-cross-origin',
            'strict-origin-when-cross-origin\n  Content-Security-Policy-Report-Only: report-uri https://api.<domain>/api/v1/csp/reports',
        );
        expect(() => renderHeaders(withPlaceholder, null)).toThrow(/placeholder tokens/);
    });
});
