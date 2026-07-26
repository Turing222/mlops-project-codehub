import react from '@vitejs/plugin-react';
import { defineConfig, configDefaults } from 'vitest/config';

export default defineConfig({
    plugins: [react()],
    server: {
        watch: {
            ignored: [
                '**/node_modules/**',
                '**/dist/**',
                '**/e2e/**',
                '**/playwright-report/**',
                '**/test-results/**',
                '**/backend/**',
                '**/logs/**',
                '**/.git/**',
                '**/.cache/**',
                '**/.pytest_cache/**',
                '**/.venv/**',
            ],
        },
    },
    test: {
        environment: 'jsdom',
        globals: true,
        css: true,
        // RTL_SKIP_AUTO_CLEANUP: setup.ts owns cleanup in act(); avoids sync auto-cleanup
        // racing React 19 scheduler work after our flush (see src/test/setup.ts).
        env: {
            RTL_SKIP_AUTO_CLEANUP: 'true',
        },
        // Run test files serially in a single worker: deterministic teardown ordering
        // keeps the React 19 scheduler flush in setup.ts reliable under v8 coverage.
        fileParallelism: false,
        setupFiles: ['./src/test/setup.ts'],
        exclude: [
            ...configDefaults.exclude,
            '**/e2e/**',
            '**/backend/**',
            '**/logs/**',
        ],
        testTimeout: 30000,
        hookTimeout: 30000,
        teardownTimeout: 30000,
        coverage: {
            provider: 'v8',
            reporter: ['text-summary', 'json-summary', 'html', 'lcov'],
            reportsDirectory: './coverage',
            include: ['src/**/*.{ts,tsx}'],
            exclude: [
                'src/**/*.test.{ts,tsx}',
                'src/test/**',
                'src/**/*.d.ts',
                'src/main.tsx',
            ],
            // 防回归下限（floor），不是追逐目标 —— 与 frontend/docs/standards/testing.md
            // “不为覆盖率数字写脆弱测试”一致。include 全量 src 后是“真实口径”：未被测模块
            // 也计入分母（故数值低于只算被测文件的口径）。阈值设在当前实测值下方留波动余量；
            // 覆盖率明显下滑、或新增大块未测代码才触发。实测基线见
            // docs/assessments/2026-06-14-frontend-cicd.md §9。
            thresholds: {
                statements: 40,
                branches: 30,
                functions: 35,
                lines: 40,
            },
        },
    },
});
