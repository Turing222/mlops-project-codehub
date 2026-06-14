"""Repo analysis TaskIQ tasks.

职责：在 worker 中执行 GitHub README-only 可信度初筛。
边界：Web 侧只投递任务；GitHub 拉取、证据提取和报告生成在本模块触发的 workflow 中完成。
"""

import logging
import uuid

from backend.application.repo_analysis.worker_workflow import RepoAnalysisWorkerWorkflow
from backend.core.exceptions import app_service_error, app_validation_error
from backend.infra.task_broker import broker
from backend.observability.trace_utils import trace_span, use_trace_context
from backend.services.repo_analysis_service import RepoAnalysisService
from backend.services.task_service import TaskService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.worker.dependencies import get_worker_session_factory

logger = logging.getLogger(__name__)


@broker.task(task_name="analyze_repo_readme")
async def analyze_repo_readme_task(
    run_id: str,
    task_id: str,
    trace_context: dict[str, str] | None = None,
) -> None:
    """TaskIQ 入口：恢复 trace context 后执行 repo README 初筛。"""
    with use_trace_context(trace_context):
        await _analyze_repo_readme_task(run_id=run_id, task_id=task_id)


async def _analyze_repo_readme_task(*, run_id: str, task_id: str) -> None:
    logger.info("TaskIQ 开始 repo analysis: run_id=%s task_id=%s", run_id, task_id)
    try:
        run_uuid = uuid.UUID(run_id)
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise app_validation_error(
            "任务参数非法: run_id/task_id 必须为 UUID",
            code="REPO_ANALYSIS_TASK_INVALID_ARGUMENT",
        ) from exc

    uow = SQLAlchemyUnitOfWork(get_worker_session_factory())
    workflow = RepoAnalysisWorkerWorkflow(
        repo_analysis_service=RepoAnalysisService(uow),
        task_service=TaskService(uow),
    )
    try:
        with trace_span(
            "taskiq.repo_analysis.readme.run",
            {"repo_analysis.run_id": run_id, "task.id": task_id},
        ):
            await workflow.run(run_id=run_uuid, task_id=task_uuid)
    except Exception as exc:
        logger.exception(
            "TaskIQ repo analysis 失败: run_id=%s task_id=%s",
            run_id,
            task_id,
        )
        raise app_service_error(
            "仓库分析失败，请稍后重试",
            code="REPO_ANALYSIS_TASK_FAILED",
        ) from exc

    logger.info("TaskIQ 完成 repo analysis: run_id=%s task_id=%s", run_id, task_id)
