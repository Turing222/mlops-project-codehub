import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { message } from 'antd';
import {
  useKBTaskStatusQuery,
  useUploadKBFileMutation,
} from '../../query/hooks/knowledge';
import { knowledgeKeys } from '../../query/keys/knowledge';
import { createInitialIngestionSteps } from '../../types/agent-trace';
import type { AgentTraceStep } from '../../types/agent-trace';
import {
  mapIngestionProgress,
  markIngestionDeadlineError,
} from './map-ingestion-progress';

const INGESTION_DEADLINE_MS = 120_000;
const TAB_SWITCH_DELAY_MS = 4_000;

export type UseKbIngestionReturn = {
  activeTraceTab: 'rag' | 'ingestion';
  setActiveTraceTab: (tab: 'rag' | 'ingestion') => void;
  ingestionSteps: AgentTraceStep[];
  uploadKBFile: (file: File) => Promise<void>;
  isIngesting: boolean;
  isIngestionSidebarOpen: boolean;
  setIsIngestionSidebarOpen: (open: boolean) => void;
  resetIngestion: () => void;
};

export function useKbIngestion({
  userId,
}: {
  userId: string | null | undefined;
}): UseKbIngestionReturn {
  const queryClient = useQueryClient();
  const { mutateAsync: uploadFileAsync } = useUploadKBFileMutation();

  const [activeTraceTab, setActiveTraceTab] = useState<'rag' | 'ingestion'>('rag');
  const [ingestionSteps, setIngestionSteps] = useState<AgentTraceStep[]>(
    createInitialIngestionSteps(),
  );
  const [isIngesting, setIsIngesting] = useState(false);
  const [isIngestionSidebarOpen, setIsIngestionSidebarOpen] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [pollingEnabled, setPollingEnabled] = useState(false);

  const deadlineTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tabSwitchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Monotonic generation; deadline / reset / new upload invalidate prior work. */
  const ingestionGenerationRef = useRef(0);
  const activeTaskIdRef = useRef<string | null>(null);
  const handledTerminalTaskRef = useRef<string | null>(null);
  const lastLoggedErrorAtRef = useRef(0);

  const clearTimers = useCallback(() => {
    if (deadlineTimerRef.current) {
      clearTimeout(deadlineTimerRef.current);
      deadlineTimerRef.current = null;
    }
    if (tabSwitchTimerRef.current) {
      clearTimeout(tabSwitchTimerRef.current);
      tabSwitchTimerRef.current = null;
    }
  }, []);

  const stopPolling = useCallback((taskIdToCancel?: string | null) => {
    const taskId = taskIdToCancel ?? activeTaskIdRef.current;
    setPollingEnabled(false);
    setActiveTaskId(null);
    activeTaskIdRef.current = null;
    if (deadlineTimerRef.current) {
      clearTimeout(deadlineTimerRef.current);
      deadlineTimerRef.current = null;
    }
    if (taskId) {
      void queryClient.cancelQueries({ queryKey: knowledgeKeys.task(taskId) });
    }
  }, [queryClient]);

  const resetIngestion = useCallback(() => {
    ingestionGenerationRef.current += 1;
    clearTimers();
    stopPolling();
    handledTerminalTaskRef.current = null;
    lastLoggedErrorAtRef.current = 0;
    setIngestionSteps(createInitialIngestionSteps());
    setActiveTraceTab('rag');
    setIsIngestionSidebarOpen(false);
    setIsIngesting(false);
  }, [clearTimers, stopPolling]);

  useEffect(() => {
    return () => {
      ingestionGenerationRef.current += 1;
      clearTimers();
      stopPolling();
    };
  }, [clearTimers, stopPolling]);

  const scheduleTabSwitchToRag = useCallback((generation: number) => {
    if (tabSwitchTimerRef.current) {
      clearTimeout(tabSwitchTimerRef.current);
    }
    tabSwitchTimerRef.current = setTimeout(() => {
      if (generation !== ingestionGenerationRef.current) return;
      setActiveTraceTab('rag');
      tabSwitchTimerRef.current = null;
    }, TAB_SWITCH_DELAY_MS);
  }, []);

  const startDeadline = useCallback((generation: number, taskId: string) => {
    if (deadlineTimerRef.current) {
      clearTimeout(deadlineTimerRef.current);
    }
    deadlineTimerRef.current = setTimeout(() => {
      deadlineTimerRef.current = null;
      if (generation !== ingestionGenerationRef.current) return;
      if (activeTaskIdRef.current !== taskId) return;

      // Terminate generation before cancel so late Query responses cannot commit.
      ingestionGenerationRef.current += 1;
      stopPolling(taskId);
      setIsIngesting(false);
      setIngestionSteps((prev) => markIngestionDeadlineError(prev, Date.now()));
      message.error('文件入库超时，请前往后台查看任务状态。');
    }, INGESTION_DEADLINE_MS);
  }, [stopPolling]);

  const taskQuery = useKBTaskStatusQuery(activeTaskId, {
    enabled: pollingEnabled && !!activeTaskId,
  });

  // Bridge server task poll → local step UI. External Query data is the source;
  // local steps remain the render source of truth for upload-only / deadline paths.
  useEffect(() => {
    if (!pollingEnabled || !activeTaskId) return;
    if (!taskQuery.data) return;

    const generation = ingestionGenerationRef.current;
    const taskId = activeTaskId;
    if (activeTaskIdRef.current !== taskId) return;
    if (handledTerminalTaskRef.current === taskId) return;

    const status = taskQuery.data.status.toLowerCase();
    const now = Date.now();
    const taskData = taskQuery.data;

    // eslint-disable-next-line react-hooks/set-state-in-effect -- sync poll snapshot into step UI
    setIngestionSteps((prev) => mapIngestionProgress(prev, taskData, now));

    if (status === 'completed') {
      if (generation !== ingestionGenerationRef.current) return;
      if (activeTaskIdRef.current !== taskId) return;
      handledTerminalTaskRef.current = taskId;
      stopPolling(taskId);
      setIsIngesting(false);
      message.success('文件入库成功！');
      scheduleTabSwitchToRag(generation);
      return;
    }

    if (status === 'failed') {
      if (generation !== ingestionGenerationRef.current) return;
      if (activeTaskIdRef.current !== taskId) return;
      handledTerminalTaskRef.current = taskId;
      stopPolling(taskId);
      setIsIngesting(false);
      message.error(taskData.error_log || '文件入库失败，请查看右侧诊断！');
    }
  }, [
    pollingEnabled,
    activeTaskId,
    taskQuery.data,
    stopPolling,
    scheduleTabSwitchToRag,
  ]);

  // Transient query errors: keep steps, log only; interval continues within deadline.
  useEffect(() => {
    if (!pollingEnabled || !activeTaskId) return;
    if (!taskQuery.isError || !taskQuery.error) return;
    if (taskQuery.errorUpdatedAt === lastLoggedErrorAtRef.current) return;
    lastLoggedErrorAtRef.current = taskQuery.errorUpdatedAt;
    console.error('轮询入库任务状态失败:', taskQuery.error);
  }, [
    pollingEnabled,
    activeTaskId,
    taskQuery.isError,
    taskQuery.error,
    taskQuery.errorUpdatedAt,
  ]);

  const uploadKBFile = useCallback(async (file: File) => {
    if (userId == null) return;

    const suffix = file.name.split('.').pop()?.toLowerCase();
    if (suffix !== 'md' && suffix !== 'markdown') {
      message.error('仅支持上传 .md 或 .markdown 格式的文件！');
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      message.error('文件大小不能超过 20MB！');
      return;
    }

    clearTimers();
    // Invalidate prior generation (including any deadline mid-flight).
    ingestionGenerationRef.current += 1;
    const generation = ingestionGenerationRef.current;
    const previousTaskId = activeTaskIdRef.current;
    if (previousTaskId) {
      void queryClient.cancelQueries({ queryKey: knowledgeKeys.task(previousTaskId) });
    }
    stopPolling();
    handledTerminalTaskRef.current = null;
    lastLoggedErrorAtRef.current = 0;

    setIsIngesting(true);
    setActiveTraceTab('ingestion');
    setIsIngestionSidebarOpen(true);

    const now = Date.now();
    setIngestionSteps([
      {
        id: 'file-upload',
        status: 'running',
        description: `正在上传: ${file.name}`,
        startedAt: now,
        finishedAt: null,
      },
      {
        id: 'content-audit',
        status: 'idle',
        description: '等待文件解析提取',
        startedAt: null,
        finishedAt: null,
      },
      {
        id: 'semantic-chunk',
        status: 'idle',
        description: '等待分块处理',
        startedAt: null,
        finishedAt: null,
      },
      {
        id: 'vector-index',
        status: 'idle',
        description: '等待构建向量索引',
        startedAt: null,
        finishedAt: null,
      },
      {
        id: 'ingestion-complete',
        status: 'idle',
        description: '等待入库完成',
        startedAt: null,
        finishedAt: null,
      },
    ]);

    try {
      // Mutation boundary: retry:false + MutationCache telemetry; generation gate after await.
      const uploadRes = await uploadFileAsync(file);
      if (generation !== ingestionGenerationRef.current) return;

      const uploadFinishedAt = Date.now();
      setIngestionSteps((prev) =>
        prev.map((step) =>
          step.id === 'file-upload'
            ? {
                ...step,
                status: 'done' as const,
                finishedAt: uploadFinishedAt,
                durationMs: uploadFinishedAt - now,
                description: `已成功上传: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`,
              }
            : step,
        ),
      );

      if (uploadRes.deduplicated || uploadRes.task_status === 'completed') {
        const completeTime = Date.now();
        setIngestionSteps((prev) =>
          prev.map((step) => {
            if (step.id === 'file-upload') return step;
            return {
              ...step,
              status: 'done' as const,
              startedAt: step.startedAt ?? uploadFinishedAt,
              finishedAt: completeTime,
              description:
                step.id === 'ingestion-complete'
                  ? '知识库文档秒传匹配成功，入库完成！'
                  : '已完成(秒传缓存)',
            };
          }),
        );
        setIsIngesting(false);
        message.success('文件入库成功 (秒传匹配)！');
        scheduleTabSwitchToRag(generation);
        return;
      }

      const taskId = uploadRes.task_id;
      if (generation !== ingestionGenerationRef.current) return;

      setIngestionSteps((prev) =>
        prev.map((step) =>
          step.id === 'content-audit'
            ? { ...step, status: 'running' as const, startedAt: Date.now() }
            : step,
        ),
      );

      activeTaskIdRef.current = taskId;
      setActiveTaskId(taskId);
      setPollingEnabled(true);
      // Wall-clock deadline starts when polling is armed (not after each request).
      startDeadline(generation, taskId);
    } catch (err: unknown) {
      if (generation !== ingestionGenerationRef.current) return;
      console.error('上传文件失败:', err);
      const errMsg = err instanceof Error ? err.message : '文件上传失败';
      setIsIngesting(false);
      setIngestionSteps((prev) =>
        prev.map((step) => {
          if (step.id === 'file-upload') {
            return {
              ...step,
              status: 'error' as const,
              finishedAt: Date.now(),
              description: `上传失败: ${errMsg}`,
            };
          }
          if (step.id === 'ingestion-complete') {
            return {
              ...step,
              status: 'error' as const,
              finishedAt: Date.now(),
              description: '处理中断',
            };
          }
          return step;
        }),
      );
      message.error(errMsg);
    }
  }, [
    userId,
    clearTimers,
    stopPolling,
    queryClient,
    uploadFileAsync,
    scheduleTabSwitchToRag,
    startDeadline,
  ]);

  return {
    activeTraceTab,
    setActiveTraceTab,
    ingestionSteps,
    uploadKBFile,
    isIngesting,
    isIngestionSidebarOpen,
    setIsIngestionSidebarOpen,
    resetIngestion,
  };
}
