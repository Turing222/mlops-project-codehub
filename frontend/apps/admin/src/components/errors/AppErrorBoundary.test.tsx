import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { AppErrorBoundary } from './AppErrorBoundary';

const { reportFrontendErrorEvent } = vi.hoisted(() => ({
    reportFrontendErrorEvent: vi.fn(),
}));
vi.mock('../../lib/http/telemetry', () => ({
    reportFrontendErrorEvent,
    normalizeErrorMessage: (error: unknown) =>
        error instanceof Error ? error.message : String(error),
}));

const Boom = (): never => {
    throw new Error('render crash');
};

describe('AppErrorBoundary', () => {
    beforeEach(() => {
        reportFrontendErrorEvent.mockClear();
    });

    it('renders children and reports nothing when there is no error', () => {
        render(
            <AppErrorBoundary>
                <div>safe content</div>
            </AppErrorBoundary>,
        );

        expect(screen.getByText('safe content')).toBeInTheDocument();
        expect(reportFrontendErrorEvent).not.toHaveBeenCalled();
    });

    it('renders the fallback and reports a render_error when a child throws', () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

        render(
            <AppErrorBoundary>
                <Boom />
            </AppErrorBoundary>,
        );

        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(reportFrontendErrorEvent).toHaveBeenCalledWith(
            expect.objectContaining({
                eventType: 'render_error',
                source: 'react_error_boundary',
                message: 'render crash',
                metadata: expect.objectContaining({
                    componentStack: expect.any(String),
                }),
            }),
        );

        consoleError.mockRestore();
    });

    it('renders a custom fallback when provided', () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

        render(
            <AppErrorBoundary fallback={<div>custom fallback</div>}>
                <Boom />
            </AppErrorBoundary>,
        );

        expect(screen.getByText('custom fallback')).toBeInTheDocument();

        consoleError.mockRestore();
    });
});
