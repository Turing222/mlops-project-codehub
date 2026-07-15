import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { message } from 'antd';
import { useKbIngestion } from './use-kb-ingestion';
import { createTestQueryClient } from '../../test/render-with-query';
import { useAuthStore } from '../../stores/auth-store';
import { knowledgeKeys } from '../../query/keys/knowledge';

vi.mock('../../api/knowledge', () => ({
  uploadKBFileAPI: vi.fn(),
  getKBTaskStatusAPI: vi.fn(),
  getDefaultKBAPI: vi.fn(),
  getDefaultKBFilesAPI: vi.fn(),
  deleteKBFileAPI: vi.fn(),
}));

vi.mock('../../query/hooks/auth', () => ({
  useMeQuery: vi.fn(),
}));

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>();
  return {
    ...actual,
    message: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
      info: vi.fn(),
    },
  };
});

import { getKBTaskStatusAPI, uploadKBFileAPI } from '../../api/knowledge';
import { useMeQuery } from '../../query/hooks/auth';

const mockUploadKBFileAPI = vi.mocked(uploadKBFileAPI);
const mockGetKBTaskStatusAPI = vi.mocked(getKBTaskStatusAPI);
const mockUseMeQuery = vi.mocked(useMeQuery);
const mockMessageSuccess = vi.mocked(message.success);
const mockMessageError = vi.mocked(message.error);

function createWrapper(queryClient = createTestQueryClient()) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

type MeQueryReturn = ReturnType<typeof useMeQuery>;

function mockMe(overrides: Partial<MeQueryReturn> = {}): MeQueryReturn {
  return {
    data: { id: '1', username: 'alice' },
    dataUpdatedAt: 0,
    error: null,
    errorUpdatedAt: 0,
    failureCount: 0,
    failureReason: null,
    errorUpdateCount: 0,
    isError: false,
    isFetched: true,
    isFetchedAfterMount: true,
    isFetching: false,
    isPaused: false,
    isLoading: false,
    isLoadingError: false,
    isInitialLoading: false,
    isPending: false,
    isPlaceholderData: false,
    isRefetchError: false,
    isRefetching: false,
    isStale: false,
    isSuccess: true,
    refetch: vi.fn(),
    status: 'success',
    fetchStatus: 'idle',
    promise: Promise.resolve({ id: '1', username: 'alice' }),
    ...overrides,
  } as MeQueryReturn;
}

function authedMe() {
  mockUseMeQuery.mockReturnValue(mockMe());
  useAuthStore.getState().setToken('tok');
}

function pendingTask(overrides: Record<string, unknown> = {}) {
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

function mdFile(name = 'doc.md', size = 100) {
  const content = 'x'.repeat(size);
  return new File([content], name, { type: 'text/markdown' });
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.getState().resetAll();
  authedMe();
  mockUploadKBFileAPI.mockResolvedValue({
    task_id: 'task-1',
    file_id: 'file-1',
    file_status: 'PENDING',
    task_status: 'pending',
    deduplicated: false,
  });
  mockGetKBTaskStatusAPI.mockResolvedValue(pendingTask());
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useKbIngestion', () => {
  it('rejects non-markdown and oversized files without uploading', async () => {
    const { result } = renderHook(() => useKbIngestion({ userId: '1' }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.uploadKBFile(new File(['x'], 'doc.txt', { type: 'text/plain' }));
    });
    expect(mockMessageError).toHaveBeenCalledWith(
      '仅支持上传 .md 或 .markdown 格式的文件！',
    );
    expect(mockUploadKBFileAPI).not.toHaveBeenCalled();

    const big = new File([new Uint8Array(20 * 1024 * 1024 + 1)], 'big.md', {
      type: 'text/markdown',
    });
    await act(async () => {
      await result.current.uploadKBFile(big);
    });
    expect(mockMessageError).toHaveBeenCalledWith('文件大小不能超过 20MB！');
    expect(mockUploadKBFileAPI).not.toHaveBeenCalled();
  });

  it('completes instantly on deduplicated/秒传 upload', async () => {
    vi.useFakeTimers();
    mockUploadKBFileAPI.mockResolvedValue({
      task_id: 'task-dup',
      file_id: 'file-dup',
      file_status: 'READY',
      task_status: 'completed',
      deduplicated: true,
    });

    const { result } = renderHook(() => useKbIngestion({ userId: '1' }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.uploadKBFile(mdFile());
    });

    expect(result.current.isIngesting).toBe(false);
    expect(result.current.ingestionSteps.every((s) => s.status === 'done')).toBe(true);
    expect(mockMessageSuccess).toHaveBeenCalledWith('文件入库成功 (秒传匹配)！');
    expect(result.current.activeTraceTab).toBe('ingestion');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(result.current.activeTraceTab).toBe('rag');
    expect(mockGetKBTaskStatusAPI).not.toHaveBeenCalled();
  });

  it('maps active progress then completes via task query polling', async () => {
    mockGetKBTaskStatusAPI
      .mockResolvedValueOnce(pendingTask({ progress: 10, payload: { file_status: 'PARSING' } }))
      .mockResolvedValueOnce(pendingTask({ progress: 45, payload: { file_status: 'CHUNKING' } }))
      .mockResolvedValue(
        pendingTask({
          status: 'completed',
          progress: 100,
          payload: { file_status: 'READY' },
        }),
      );

    const { result } = renderHook(() => useKbIngestion({ userId: '1' }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.uploadKBFile(mdFile());
    });

    expect(result.current.isIngesting).toBe(true);
    expect(result.current.activeTraceTab).toBe('ingestion');

    await waitFor(
      () => {
        expect(result.current.isIngesting).toBe(false);
      },
      { timeout: 5000 },
    );
    expect(result.current.ingestionSteps.every((s) => s.status === 'done')).toBe(true);
    expect(mockMessageSuccess).toHaveBeenCalledWith('文件入库成功！');
  });

  it('handles failed task terminal state', async () => {
    mockGetKBTaskStatusAPI.mockResolvedValue(
      pendingTask({ status: 'failed', error_log: 'parse boom' }),
    );

    const { result } = renderHook(() => useKbIngestion({ userId: '1' }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.uploadKBFile(mdFile());
    });

    await waitFor(
      () => {
        expect(result.current.isIngesting).toBe(false);
      },
      { timeout: 5000 },
    );
    expect(
      result.current.ingestionSteps.find((s) => s.id === 'ingestion-complete')?.description,
    ).toBe('parse boom');
    expect(mockMessageError).toHaveBeenCalledWith('parse boom');
  });

  it('keeps steps on transient query error and continues within deadline', async () => {
    mockGetKBTaskStatusAPI
      .mockRejectedValueOnce(new Error('blip'))
      .mockResolvedValue(
        pendingTask({
          status: 'completed',
          progress: 100,
          payload: { file_status: 'READY' },
        }),
      );

    const { result } = renderHook(() => useKbIngestion({ userId: '1' }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.uploadKBFile(mdFile());
    });

    await waitFor(
      () => {
        expect(result.current.isIngesting).toBe(false);
      },
      { timeout: 5000 },
    );
    expect(result.current.ingestionSteps.every((s) => s.status === 'done')).toBe(true);
  });

  it('times out by 120s wall-clock deadline even with fewer than 120 attempts', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockGetKBTaskStatusAPI.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(() => {
            resolve(pendingTask({ progress: 5, payload: { file_status: 'PARSING' } }));
          }, 3000);
        }),
    );

    const { result } = renderHook(() => useKbIngestion({ userId: '1' }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.uploadKBFile(mdFile());
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });

    expect(result.current.isIngesting).toBe(false);
    expect(
      result.current.ingestionSteps.some(
        (s) => s.status === 'error' && s.description === '入库任务查询超时',
      ),
    ).toBe(true);
    expect(mockMessageError).toHaveBeenCalledWith(
      '文件入库超时，请前往后台查看任务状态。',
    );
    expect(mockGetKBTaskStatusAPI.mock.calls.length).toBeLessThan(120);
  });

  it('ignores late completed response after deadline', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let resolveTask: (value: ReturnType<typeof pendingTask>) => void = () => undefined;
    mockGetKBTaskStatusAPI.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveTask = resolve;
        }),
    );

    const queryClient = createTestQueryClient();
    const { result } = renderHook(() => useKbIngestion({ userId: '1' }), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.uploadKBFile(mdFile());
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(result.current.isIngesting).toBe(false);

    await act(async () => {
      resolveTask(
        pendingTask({
          status: 'completed',
          progress: 100,
          payload: { file_status: 'READY' },
        }),
      );
      await Promise.resolve();
    });

    expect(
      result.current.ingestionSteps.some(
        (s) => s.status === 'error' && s.description === '入库任务查询超时',
      ),
    ).toBe(true);
    expect(result.current.ingestionSteps.every((s) => s.status === 'done')).toBe(false);
  });

  it('new upload cancels previous deadline and task query', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockUploadKBFileAPI
      .mockResolvedValueOnce({
        task_id: 'task-old',
        file_id: 'file-old',
        file_status: 'PENDING',
        task_status: 'pending',
        deduplicated: false,
      })
      .mockResolvedValueOnce({
        task_id: 'task-new',
        file_id: 'file-new',
        file_status: 'READY',
        task_status: 'completed',
        deduplicated: true,
      });
    mockGetKBTaskStatusAPI.mockResolvedValue(pendingTask({ id: 'task-old' }));

    const queryClient = createTestQueryClient();
    const cancelSpy = vi.spyOn(queryClient, 'cancelQueries');

    const { result } = renderHook(() => useKbIngestion({ userId: '1' }), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.uploadKBFile(mdFile('old.md'));
    });

    await act(async () => {
      await result.current.uploadKBFile(mdFile('new.md'));
    });

    expect(cancelSpy).toHaveBeenCalledWith({
      queryKey: knowledgeKeys.task('task-old'),
    });
    expect(result.current.isIngesting).toBe(false);
    expect(mockMessageSuccess).toHaveBeenCalledWith('文件入库成功 (秒传匹配)！');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(
      result.current.ingestionSteps.some((s) => s.description === '入库任务查询超时'),
    ).toBe(false);
  });

  it('resetIngestion drops deferred upload state', async () => {
    let resolveUpload: (value: {
      task_id: string;
      file_id: string;
      file_status: string;
      task_status: string;
      deduplicated: boolean;
    }) => void = () => undefined;
    mockUploadKBFileAPI.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveUpload = resolve;
        }),
    );

    const { result } = renderHook(() => useKbIngestion({ userId: '1' }), {
      wrapper: createWrapper(),
    });

    let uploadPromise: Promise<void> | undefined;
    act(() => {
      uploadPromise = result.current.uploadKBFile(mdFile());
    });
    // mutateAsync schedules mutationFn on a microtask — flush before capturing resolve.
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.isIngesting).toBe(true);
    expect(mockUploadKBFileAPI).toHaveBeenCalled();

    act(() => {
      result.current.resetIngestion();
    });
    expect(result.current.isIngesting).toBe(false);
    expect(result.current.ingestionSteps.every((s) => s.status === 'idle')).toBe(true);

    await act(async () => {
      resolveUpload({
        task_id: 'task-stale',
        file_id: 'file-stale',
        file_status: 'READY',
        task_status: 'completed',
        deduplicated: true,
      });
      await uploadPromise;
    });

    expect(result.current.isIngesting).toBe(false);
    expect(result.current.ingestionSteps.every((s) => s.status === 'idle')).toBe(true);
    expect(mockMessageSuccess).not.toHaveBeenCalled();
  });

  it('unmount drops deferred upload response without toast or polling', async () => {
    let resolveUpload: (value: {
      task_id: string;
      file_id: string;
      file_status: string;
      task_status: string;
      deduplicated: boolean;
    }) => void = () => undefined;
    mockUploadKBFileAPI.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveUpload = resolve;
        }),
    );

    const { result, unmount } = renderHook(() => useKbIngestion({ userId: '1' }), {
      wrapper: createWrapper(),
    });

    let uploadPromise: Promise<void> | undefined;
    act(() => {
      uploadPromise = result.current.uploadKBFile(mdFile());
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.isIngesting).toBe(true);
    expect(mockUploadKBFileAPI).toHaveBeenCalled();

    unmount();

    await act(async () => {
      resolveUpload({
        task_id: 'task-after-unmount',
        file_id: 'file-after-unmount',
        file_status: 'READY',
        task_status: 'completed',
        deduplicated: true,
      });
      await uploadPromise;
    });

    expect(mockMessageSuccess).not.toHaveBeenCalled();
    expect(mockMessageError).not.toHaveBeenCalled();
    expect(mockGetKBTaskStatusAPI).not.toHaveBeenCalled();
  });

  it('does nothing when userId is missing', async () => {
    const { result } = renderHook(() => useKbIngestion({ userId: null }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.uploadKBFile(mdFile());
    });
    expect(mockUploadKBFileAPI).not.toHaveBeenCalled();
  });

  it('clears tab-switch timer on reset before 4s elapses', async () => {
    vi.useFakeTimers();
    mockUploadKBFileAPI.mockResolvedValue({
      task_id: 'task-dup',
      file_id: 'file-dup',
      file_status: 'READY',
      task_status: 'completed',
      deduplicated: true,
    });

    const { result } = renderHook(() => useKbIngestion({ userId: '1' }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.uploadKBFile(mdFile());
    });
    expect(result.current.activeTraceTab).toBe('ingestion');

    act(() => {
      result.current.resetIngestion();
    });
    expect(result.current.activeTraceTab).toBe('rag');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(result.current.activeTraceTab).toBe('rag');
  });
});
