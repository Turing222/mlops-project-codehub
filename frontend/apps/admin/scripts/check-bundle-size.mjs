import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const appDir = join(scriptDir, '..');
const assetsDir = join(appDir, 'dist', 'assets');
const baselinePath = join(appDir, 'bundle-baseline.json');

const MEASURED_EXTENSIONS = new Set(['.js', '.css']);
const DEFAULT_TOLERANCE_PERCENT = 10;
// Hints are read by users running make from the repository root, so keep the
// refresh command root-relative; the script itself resolves paths from its own
// location and works from any cwd.
const UPDATE_COMMAND = 'node frontend/apps/admin/scripts/check-bundle-size.mjs --update';

function measureTotalGzipBytes() {
    if (!existsSync(assetsDir)) {
        throw new Error(`Missing ${assetsDir}; run the build first (make frontend-build).`);
    }

    let total = 0;
    for (const name of readdirSync(assetsDir)) {
        if (!MEASURED_EXTENSIONS.has(extname(name))) {
            continue;
        }
        total += gzipSync(readFileSync(join(assetsDir, name))).length;
    }

    if (total === 0) {
        throw new Error(`No js/css assets found under ${assetsDir}; the build output looks broken.`);
    }

    return total;
}

function formatKiB(bytes) {
    return `${(bytes / 1024).toFixed(1)} KiB`;
}

const update = process.argv.includes('--update');
const total = measureTotalGzipBytes();

if (update) {
    const existingTolerance = existsSync(baselinePath)
        ? JSON.parse(readFileSync(baselinePath, 'utf8')).tolerancePercent
        : undefined;
    const tolerancePercent = Number.isFinite(existingTolerance)
        ? existingTolerance
        : DEFAULT_TOLERANCE_PERCENT;
    const baseline = { totalGzipBytes: total, tolerancePercent };
    writeFileSync(baselinePath, `${JSON.stringify(baseline, null, 2)}\n`, 'utf8');
    console.log(`Updated bundle baseline: ${formatKiB(total)} (${total} bytes).`);
    process.exit(0);
}

if (!existsSync(baselinePath)) {
    console.error(`Missing ${baselinePath}.`);
    console.error(`Run '${UPDATE_COMMAND}' after a clean build to create it.`);
    process.exit(1);
}

const baseline = JSON.parse(readFileSync(baselinePath, 'utf8'));
// A non-numeric totalGzipBytes would turn the limit into NaN and every
// comparison below into false, silently passing the check.
if (!Number.isFinite(baseline.totalGzipBytes) || baseline.totalGzipBytes <= 0) {
    console.error(`Invalid totalGzipBytes in ${baselinePath}.`);
    console.error(`Refresh it: ${UPDATE_COMMAND}`);
    process.exit(1);
}
const tolerancePercent = Number.isFinite(baseline.tolerancePercent)
    ? baseline.tolerancePercent
    : DEFAULT_TOLERANCE_PERCENT;
const limit = Math.round(baseline.totalGzipBytes * (1 + tolerancePercent / 100));
const floor = Math.round(baseline.totalGzipBytes * (1 - tolerancePercent / 100));

console.log(
    `Bundle gzip total: ${formatKiB(total)} (baseline ${formatKiB(baseline.totalGzipBytes)}, limit ${formatKiB(limit)}).`,
);

if (total > limit) {
    console.error(`Bundle gzip total exceeds the baseline by more than ${tolerancePercent}%.`);
    console.error('Inspect the growth with ANALYZE=1 (dist/stats.html).');
    console.error(`If the growth is intentional, refresh the baseline: ${UPDATE_COMMAND}`);
    process.exit(1);
}

if (total < floor) {
    console.log(
        `Bundle shrank by more than ${tolerancePercent}%; refresh the baseline to lock in the win.`,
    );
}
