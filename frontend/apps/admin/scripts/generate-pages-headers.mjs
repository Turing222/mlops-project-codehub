import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const appDir = join(scriptDir, '..');
const baseHeadersPath = join(appDir, 'public', '_headers');
const distHeadersPath = join(appDir, 'dist', '_headers');

const apiBaseUrl = process.env.VITE_API_BASE_URL?.trim();
const isCloudflarePages = process.env.CF_PAGES === '1';

function resolveApiOrigin(value) {
    if (!value) {
        if (isCloudflarePages) {
            throw new Error('VITE_API_BASE_URL is required for Cloudflare Pages CSP headers.');
        }
        return null;
    }

    const url = new URL(value);
    if (isCloudflarePages && url.protocol !== 'https:') {
        throw new Error('VITE_API_BASE_URL must be an https origin for Cloudflare Pages CSP headers.');
    }
    if (url.hostname.includes('<') || url.hostname.includes('>')) {
        throw new Error('VITE_API_BASE_URL must not contain placeholder tokens.');
    }

    return url.origin;
}

function buildCsp(apiOrigin) {
    return [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob: https://mermaid.ink",
        `connect-src 'self' ${apiOrigin}`,
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'self'",
        `report-uri ${apiOrigin}/api/v1/csp/reports`,
    ].join('; ');
}

const apiOrigin = resolveApiOrigin(apiBaseUrl);
let headers = await readFile(baseHeadersPath, 'utf8');

if (apiOrigin) {
    headers = headers.replace(
        '  Referrer-Policy: strict-origin-when-cross-origin',
        [
            '  Referrer-Policy: strict-origin-when-cross-origin',
            `  Content-Security-Policy-Report-Only: ${buildCsp(apiOrigin)}`,
        ].join('\n'),
    );
    if (!headers.includes('Content-Security-Policy-Report-Only')) {
        throw new Error('Generated _headers must include Content-Security-Policy-Report-Only.');
    }
}

if (headers.includes('<domain>')) {
    throw new Error('Generated _headers must not contain placeholder tokens.');
}

await writeFile(distHeadersPath, headers, 'utf8');
