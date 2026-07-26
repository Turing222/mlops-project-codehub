import { describe, expect, it } from 'vitest';
import type { KBTaskResponse } from '../../schemas/chat';
import type { AgentTraceStep } from '../../types/agent-trace';
import {
  mapIngestionProgress,
  markIngestionDeadlineError,
} from './map-ingestion-progress';

function baseSteps(): AgentTraceStep[] {
  return [
    {
      id: 'file-upload',
      status: 'done',
      description: 'uploaded',
      startedAt: 1,
      finishedAt: 2,
    },
    {
      id: 'content-audit',
      status: 'running',
      description: 'parsing',
      startedAt: 3,
      finishedAt: null,
    },
    {
      id: 'semantic-chunk',
      status: 'idle',
      description: 'wait',
      startedAt: null,
      finishedAt: null,
    },
    {
      id: 'vector-index',
      status: 'idle',
      description: 'wait',
      startedAt: null,
      finishedAt: null,
    },
    {
      id: 'ingestion-complete',
      status: 'idle',
      description: 'wait',
      startedAt: null,
      finishedAt: null,
    },
  ];
}

function task(overrides: Partial<KBTaskResponse> = {}): KBTaskResponse {
  return {
    id: 'task-1',
    action_type: 'ingest',
    status: 'running',
    progress: 10,
    payload: { file_status: 'PARSING' },
    error_log: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('mapIngestionProgress', () => {
  it('maps active progress stages from payload and progress', () => {
    const mid = mapIngestionProgress(
      baseSteps(),
      task({ progress: 45, payload: { file_status: 'CHUNKING' } }),
      1000,
    );
    expect(mid.find((s) => s.id === 'content-audit')?.status).toBe('done');
    expect(mid.find((s) => s.id === 'semantic-chunk')?.status).toBe('running');

    const indexing = mapIngestionProgress(
      mid,
      task({ progress: 80, payload: { file_status: 'INDEXING' } }),
      2000,
    );
    expect(indexing.find((s) => s.id === 'semantic-chunk')?.status).toBe('done');
    expect(indexing.find((s) => s.id === 'vector-index')?.status).toBe('running');
    expect(indexing.find((s) => s.id === 'vector-index')?.metricDetails).toEqual({
      '入库进度': '80%',
    });
  });

  it('marks all remaining steps done on completed', () => {
    const next = mapIngestionProgress(
      baseSteps(),
      task({ status: 'completed', progress: 100, payload: { file_status: 'READY' } }),
      3000,
    );
    expect(next.every((s) => s.status === 'done')).toBe(true);
    expect(next.find((s) => s.id === 'ingestion-complete')?.description).toContain(
      '建索入库',
    );
  });

  it('marks running/idle steps as error on failed', () => {
    const next = mapIngestionProgress(
      baseSteps(),
      task({ status: 'failed', error_log: 'boom' }),
      4000,
    );
    expect(next.find((s) => s.id === 'file-upload')?.status).toBe('done');
    expect(next.find((s) => s.id === 'content-audit')?.status).toBe('error');
    expect(next.find((s) => s.id === 'ingestion-complete')?.description).toBe('boom');
  });

  it('ignores non-string payload.file_status without throwing', () => {
    const withNumber = mapIngestionProgress(
      baseSteps(),
      task({ progress: 10, payload: { file_status: 42 } }),
      1000,
    );
    expect(withNumber.find((s) => s.id === 'content-audit')?.status).toBe('running');

    const withObject = mapIngestionProgress(
      baseSteps(),
      task({ progress: 10, payload: { file_status: { code: 'PARSING' } } }),
      1000,
    );
    expect(withObject.find((s) => s.id === 'content-audit')?.status).toBe('running');

    // Falls back to progress thresholds when file_status is unusable.
    const byProgress = mapIngestionProgress(
      baseSteps(),
      task({ progress: 45, payload: { file_status: null } }),
      1000,
    );
    expect(byProgress.find((s) => s.id === 'content-audit')?.status).toBe('done');
    expect(byProgress.find((s) => s.id === 'semantic-chunk')?.status).toBe('running');
  });
});

describe('markIngestionDeadlineError', () => {
  it('errors running and idle steps only', () => {
    const next = markIngestionDeadlineError(baseSteps(), 5000);
    expect(next.find((s) => s.id === 'file-upload')?.status).toBe('done');
    expect(next.find((s) => s.id === 'content-audit')?.status).toBe('error');
    expect(next.find((s) => s.id === 'content-audit')?.description).toBe(
      '入库任务查询超时',
    );
    expect(next.find((s) => s.id === 'semantic-chunk')?.status).toBe('error');
  });
});
