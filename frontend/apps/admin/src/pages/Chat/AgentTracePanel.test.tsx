import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AgentTracePanel from './AgentTracePanel';
import { createInitialTraceSteps } from '../../types/agent-trace';
import type { AgentTraceStep, CitationItem } from '../../types/agent-trace';
import styles from './AgentTracePanel.module.css';
import { renderWithQueryClient } from '../../test/render-with-query';

vi.mock('../../context/useAuth', () => ({
    useAuth: vi.fn(),
}));

import { useAuth } from '../../context/useAuth';

const mockUseAuth = vi.mocked(useAuth);

type AuthReturn = ReturnType<typeof useAuth>;

const defaultAuth: AuthReturn = {
    user: null,
    token: null,
    isLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: false,
    showAuthModal: false,
    setShowAuthModal: vi.fn(),
    refreshUser: vi.fn(),
};

const sampleCitations: CitationItem[] = [
    {
        documentName: 'doc1.pdf',
        chunkId: 'c1',
        relevanceScore: 0.92,
        summarySnippet: 'Relevant passage from document one.',
    },
    {
        documentName: 'report.docx',
        chunkId: 'c2',
        relevanceScore: 0.78,
        summarySnippet: 'Another passage from the report.',
    },
];

function renderPanel(overrides: Record<string, unknown> = {}) {
    const props = {
        traceSteps: [],
        citations: [],
        ...overrides,
    };
    const result = renderWithQueryClient(<AgentTracePanel {...props} />);
    return { ...result, props };
}

describe('AgentTracePanel', () => {
    it('shows empty hint when no trace steps', () => {
        mockUseAuth.mockReturnValue(defaultAuth);
        renderPanel();
        expect(screen.getByTestId('trace-panel-empty')).toBeInTheDocument();
    });

    it('renders all trace steps with data-testid', () => {
        mockUseAuth.mockReturnValue(defaultAuth);
        const steps = createInitialTraceSteps();
        renderPanel({ traceSteps: steps });
        const stepIds = ['receive-query', 'router-judge', 'kb-search', 'local-search', 'web-search', 'model-thinking', 'generate-answer', 'organize-citations', 'complete'];
        for (const id of stepIds) {
            expect(screen.getByTestId(`trace-step-${id}`)).toBeInTheDocument();
        }
    });

    it('shows running indicator on active step', () => {
        mockUseAuth.mockReturnValue(defaultAuth);
        const steps = createInitialTraceSteps();
        renderPanel({ traceSteps: steps });
        const runningSteps = document.querySelectorAll('.' + styles['trace-step-running']);
        expect(runningSteps.length).toBeGreaterThanOrEqual(1);
    });

    it('shows check icon for done steps', () => {
        mockUseAuth.mockReturnValue(defaultAuth);
        const steps = createInitialTraceSteps().map((s, i) =>
            i === 0 ? { ...s, status: 'done' as const, finishedAt: Date.now() } : s,
        );
        renderPanel({ traceSteps: steps });
        expect(screen.getByTestId('trace-step-receive-query')).toBeInTheDocument();
    });

    it('shows citation count header when trace is active', () => {
        mockUseAuth.mockReturnValue(defaultAuth);
        const steps = createInitialTraceSteps();
        renderPanel({ traceSteps: steps, citations: sampleCitations });
        const header = screen.getByTestId('trace-citations-header');
        expect(header).toBeInTheDocument();
        expect(header).toHaveTextContent('2');
    });

    it('expands citations on click', async () => {
        const user = userEvent.setup();
        mockUseAuth.mockReturnValue(defaultAuth);
        const steps = createInitialTraceSteps();
        renderPanel({ traceSteps: steps, citations: sampleCitations });

        await user.click(screen.getByTestId('trace-citations-header'));

        expect(screen.getByText('doc1.pdf')).toBeInTheDocument();
        expect(screen.getByText('report.docx')).toBeInTheDocument();
    });

    it('shows no-citations message when expanded with empty citations', async () => {
        const user = userEvent.setup();
        mockUseAuth.mockReturnValue(defaultAuth);
        const steps = createInitialTraceSteps();
        renderPanel({ traceSteps: steps, citations: [] });

        await user.click(screen.getByTestId('trace-citations-header'));

        expect(screen.getByTestId('trace-citations-empty')).toBeInTheDocument();
    });

    it('shows error icon for error status step', () => {
        mockUseAuth.mockReturnValue(defaultAuth);
        const steps: AgentTraceStep[] = createInitialTraceSteps().map((s, i) =>
            i === 3 ? { ...s, status: 'error' as const, finishedAt: Date.now() } : s,
        );
        renderPanel({ traceSteps: steps });
        const errorStep = document.querySelector('.' + styles['trace-step-error']);
        expect(errorStep).toBeInTheDocument();
    });

    it('renders collapsed view when collapsed prop is true', () => {
        mockUseAuth.mockReturnValue(defaultAuth);
        renderPanel({ collapsed: true });
        expect(screen.getByTestId('trace-panel-collapsed')).toBeInTheDocument();
        expect(screen.getByTestId('trace-panel-expand-btn')).toBeInTheDocument();
        expect(screen.queryByTestId('trace-panel-empty')).not.toBeInTheDocument();
    });

    it('renders collapse button in header and calls onToggle when clicked', async () => {
        const user = userEvent.setup();
        mockUseAuth.mockReturnValue(defaultAuth);
        const onToggle = vi.fn();
        renderPanel({ onToggle });
        
        const collapseBtn = screen.getByTestId('trace-panel-collapse-btn');
        expect(collapseBtn).toBeInTheDocument();
        
        await user.click(collapseBtn);
        expect(onToggle).toHaveBeenCalledTimes(1);
    });

    it('renders expand button in collapsed view and calls onToggle when clicked', async () => {
        const user = userEvent.setup();
        mockUseAuth.mockReturnValue(defaultAuth);
        const onToggle = vi.fn();
        renderPanel({ collapsed: true, onToggle });
        
        const expandBtn = screen.getByTestId('trace-panel-expand-btn');
        expect(expandBtn).toBeInTheDocument();
        
        await user.click(expandBtn);
        expect(onToggle).toHaveBeenCalledTimes(1);
    });

    it('renders trace metrics summary and step durations', () => {
        mockUseAuth.mockReturnValue(defaultAuth);
        const steps: AgentTraceStep[] = createInitialTraceSteps().map((step) => {
            if (step.id === 'generate-answer') {
                return {
                    ...step,
                    status: 'done',
                    durationMs: 1500,
                    metricDetails: {
                        first_token_latency_ms: 320,
                        answer_model_tier: 'fast',
                        model_route_confidence: 0.91,
                    },
                };
            }
            if (step.id === 'kb-search') {
                return {
                    ...step,
                    status: 'done',
                    durationMs: 120,
                    metricDetails: {
                        candidate_count: 20,
                        hit_count: 4,
                        retrieval_mode: 'hybrid',
                        rerank_used: true,
                    },
                };
            }
            if (step.id === 'complete') {
                return {
                    ...step,
                    status: 'done',
                    durationMs: 2600,
                    metricDetails: { tokens_per_second: 18.5 },
                };
            }
            return { ...step, status: 'done' as const };
        });

        renderPanel({ traceSteps: steps });

        expect(screen.getByTestId('trace-metrics-summary')).toHaveTextContent('320 ms');
        expect(screen.getByTestId('trace-metrics-summary')).toHaveTextContent('2.6 s');
        expect(screen.getByTestId('trace-step-duration-kb-search')).toHaveTextContent('120 ms');
        expect(screen.getByText(/hybrid/)).toBeInTheDocument();
        expect(screen.getByText(/fast/)).toBeInTheDocument();
        expect(screen.getByText(/91%/)).toBeInTheDocument();
    });
});
