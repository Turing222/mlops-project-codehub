import type { ChatStreamStepEvent } from '../../schemas/chat';
import type { ChatMessage, ChatSession, SessionDetailResponse } from '../../types/chat';
import type { AgentTraceStep, CitationItem } from '../../types/agent-trace';
import {
  applyTraceMetricsToSteps,
  parseChatMessageMetrics,
  parseCitations,
  parseRagMetrics,
  TRACE_STEP_DEFS,
} from '../../types/agent-trace';
import type { ChatMode } from './use-chat-stream-types';

/** Derive mode / citations / metric-enriched steps from history session detail. */
export function deriveHistoryPresentation(detail: SessionDetailResponse): {
  chatMode: ChatMode;
  citations: CitationItem[];
  applyMetrics: (prev: AgentTraceStep[]) => AgentTraceStep[];
} {
  const lastAssistant = [...(detail.messages || [])]
    .reverse()
    .find((m) => m.role === 'assistant');
  const lastMetrics = parseRagMetrics(lastAssistant?.search_context);
  let chatMode: ChatMode = 'normal';
  if (detail.session) {
    if (lastMetrics?.external_context_used) chatMode = 'web_rag';
    else if (detail.session.kb_id) chatMode = 'rag';
  }
  const citations = lastAssistant?.search_context
    ? parseCitations(lastAssistant.search_context)
    : [];
  return {
    chatMode,
    citations,
    applyMetrics: (prev) =>
      applyTraceMetricsToSteps(
        prev,
        parseChatMessageMetrics(lastAssistant?.message_metadata),
        parseRagMetrics(lastAssistant?.search_context),
      ),
  };
}

/** Post-stream detail: optional web_rag flip + citations + metrics. */
export function deriveAssistantDetailPresentation(
  lastAssistant: ChatMessage | undefined,
  session: ChatSession,
): {
  chatMode?: 'web_rag';
  citations: CitationItem[];
  applyMetrics: (prev: AgentTraceStep[]) => AgentTraceStep[];
} {
  const lastMetrics = parseRagMetrics(lastAssistant?.search_context);
  return {
    chatMode:
      lastMetrics?.external_context_used && session?.kb_id ? 'web_rag' : undefined,
    citations: lastAssistant?.search_context
      ? parseCitations(lastAssistant.search_context)
      : [],
    applyMetrics: (prev) =>
      applyTraceMetricsToSteps(
        prev,
        parseChatMessageMetrics(lastAssistant?.message_metadata),
        parseRagMetrics(lastAssistant?.search_context),
      ),
  };
}

/** Mark prior steps done and target running (stream step advance). */
export function advanceTraceToStep(
  prev: AgentTraceStep[],
  targetStepId: string,
): AgentTraceStep[] {
  const targetIdx = TRACE_STEP_DEFS.findIndex((d) => d.id === targetStepId);
  if (targetIdx === -1) {
    if (import.meta.env.DEV) {
      console.warn(`[advanceToStep] Unknown step id: "${targetStepId}"`);
    }
    return prev;
  }
  const now = Date.now();
  return prev.map((step, idx) => {
    if (
      idx < targetIdx &&
      step.status !== 'done' &&
      step.status !== 'error' &&
      step.status !== 'skipped'
    ) {
      return { ...step, status: 'done' as const, finishedAt: now };
    }
    if (idx === targetIdx && step.status !== 'done' && step.status !== 'error') {
      return {
        ...step,
        status: 'running' as const,
        startedAt: step.startedAt ?? now,
      };
    }
    return step;
  });
}

/** Apply a stream step event onto trace steps (may also advance priors). */
export function applyStreamStepEvent(
  prev: AgentTraceStep[],
  event: ChatStreamStepEvent,
): AgentTraceStep[] {
  const now = Date.now();
  const targetIdx = TRACE_STEP_DEFS.findIndex((def) => def.id === event.step);
  if (targetIdx === -1) return prev;

  return prev.map((step, idx) => {
    if (step.id === event.step) {
      if (event.status === 'running') {
        return {
          ...step,
          status: 'running' as const,
          startedAt: step.startedAt ?? now,
        };
      }
      if (event.status === 'skipped') {
        return { ...step, status: 'skipped' as const, finishedAt: now };
      }
      const durationMs =
        step.startedAt !== null ? now - step.startedAt : step.durationMs;
      return {
        ...step,
        status: 'done' as const,
        finishedAt: now,
        durationMs,
        metricDetails: event.metrics,
      };
    }
    if (
      event.status === 'running' &&
      idx < targetIdx &&
      step.status !== 'done' &&
      step.status !== 'error' &&
      step.status !== 'skipped'
    ) {
      return { ...step, status: 'done' as const, finishedAt: now };
    }
    return step;
  });
}

export function markReceiveQueryNetwork(
  prev: AgentTraceStep[],
  networkMs: number,
): AgentTraceStep[] {
  return prev.map((step) =>
    step.id === 'receive-query'
      ? {
          ...step,
          status: 'done' as const,
          finishedAt: Date.now(),
          durationMs: networkMs,
          description: '网络连接建立成功',
        }
      : step,
  );
}

export function applyMetaModeSkips(
  prev: AgentTraceStep[],
  mode: ChatMode,
): AgentTraceStep[] {
  const now = Date.now();
  return prev.map((step) => {
    if (step.id === 'receive-query') {
      return { ...step, status: 'done' as const, finishedAt: now };
    }
    if (step.id === 'kb-search' && mode === 'normal') {
      return { ...step, status: 'skipped' as const, finishedAt: now };
    }
    if (step.id === 'local-search') {
      return { ...step, status: 'skipped' as const, finishedAt: now };
    }
    if (step.id === 'web-search' && (mode === 'normal' || mode === 'rag')) {
      return { ...step, status: 'skipped' as const, finishedAt: now };
    }
    return step;
  });
}

export function completeIdleTraceSteps(prev: AgentTraceStep[]): AgentTraceStep[] {
  const now = Date.now();
  return prev.map((step) => {
    if (
      step.status !== 'done' &&
      step.status !== 'error' &&
      step.status !== 'skipped'
    ) {
      return { ...step, status: 'done' as const, finishedAt: now };
    }
    return step;
  });
}

export function markRunningTraceError(prev: AgentTraceStep[]): AgentTraceStep[] {
  const now = Date.now();
  const runningIdx = prev.findIndex((s) => s.status === 'running');
  return prev.map((step, idx) => {
    if (idx === runningIdx) {
      return { ...step, status: 'error' as const, finishedAt: now };
    }
    if (idx > runningIdx && step.status === 'idle') {
      return { ...step, status: 'skipped' as const };
    }
    return step;
  });
}
