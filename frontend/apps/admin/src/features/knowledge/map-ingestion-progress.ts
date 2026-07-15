import type { KBTaskResponse } from '../../schemas/chat';
import type { AgentTraceStep } from '../../types/agent-trace';

/**
 * Pure mapping from KB task poll response -> ingestion UI steps.
 * Must not toast, start timers, or touch Query side effects.
 */
export function mapIngestionProgress(
  steps: AgentTraceStep[],
  taskRes: KBTaskResponse,
  now: number,
): AgentTraceStep[] {
  const currentStatus = taskRes.status.toLowerCase();
  const progress = taskRes.progress;
  const rawFileStatus = taskRes.payload?.file_status;
  const fileStatusFromPayload =
    typeof rawFileStatus === 'string' ? rawFileStatus.toUpperCase() : undefined;

  return steps.map((step) => {
    if (step.id === 'file-upload') return step;

    if (currentStatus === 'completed') {
      return {
        ...step,
        status: 'done' as const,
        startedAt: step.startedAt ?? now,
        finishedAt: step.finishedAt ?? now,
        description:
          step.id === 'ingestion-complete'
            ? '文档已成功解析、切片并建索入库！'
            : step.description || '已完成',
        metricDetails:
          step.id === 'vector-index'
            ? { '入库进度': '100%' }
            : step.metricDetails,
      };
    }

    if (currentStatus === 'failed') {
      if (step.id === 'ingestion-complete') {
        return {
          ...step,
          status: 'error' as const,
          finishedAt: now,
          description:
            taskRes.error_log || '知识文件入库失败，详细信息见错误日志',
        };
      }
      if (step.status === 'running' || step.status === 'idle') {
        return {
          ...step,
          status: 'error' as const,
          finishedAt: now,
          description: '处理中断',
        };
      }
      return step;
    }

    if (step.id === 'content-audit') {
      if (fileStatusFromPayload === 'PARSING' || progress < 30) {
        return {
          ...step,
          status: 'running' as const,
          startedAt: step.startedAt ?? now,
          description: '正在解析提取文档文本内容...',
        };
      }
      return {
        ...step,
        status: 'done' as const,
        startedAt: step.startedAt ?? now,
        finishedAt: step.finishedAt ?? now,
        description: '文档文本内容已成功提取',
      };
    }

    if (step.id === 'semantic-chunk') {
      if (fileStatusFromPayload === 'CHUNKING' || (progress >= 30 && progress < 60)) {
        return {
          ...step,
          status: 'running' as const,
          startedAt: step.startedAt ?? now,
          description: '正在进行智能文本切片与安全扫描...',
        };
      }
      if (progress >= 60 || fileStatusFromPayload === 'READY') {
        return {
          ...step,
          status: 'done' as const,
          startedAt: step.startedAt ?? now,
          finishedAt: step.finishedAt ?? now,
          description: '文本切片及分块安全扫描已完成',
        };
      }
      return step;
    }

    if (step.id === 'vector-index') {
      if (progress >= 60 && progress < 100) {
        return {
          ...step,
          status: 'running' as const,
          startedAt: step.startedAt ?? now,
          description: '正在计算向量嵌入并写入向量数据库...',
          metricDetails: { '入库进度': `${progress}%` },
        };
      }
      if (progress >= 100 || fileStatusFromPayload === 'READY') {
        return {
          ...step,
          status: 'done' as const,
          startedAt: step.startedAt ?? now,
          finishedAt: step.finishedAt ?? now,
          description: '向量索引构建完成',
          metricDetails: { '入库进度': '100%' },
        };
      }
      return step;
    }

    if (step.id === 'ingestion-complete') {
      if (progress >= 100 || fileStatusFromPayload === 'READY') {
        return {
          ...step,
          status: 'done' as const,
          startedAt: step.startedAt ?? now,
          finishedAt: now,
          description: '文档入库全生命周期执行完成！',
        };
      }
      return step;
    }

    return step;
  });
}

export function markIngestionDeadlineError(
  steps: AgentTraceStep[],
  now: number,
): AgentTraceStep[] {
  return steps.map((step) =>
    step.status === 'running' || step.status === 'idle'
      ? {
          ...step,
          status: 'error' as const,
          finishedAt: now,
          description: '入库任务查询超时',
        }
      : step,
  );
}
