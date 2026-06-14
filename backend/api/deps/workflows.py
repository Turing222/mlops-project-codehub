import redis.asyncio as redis
from fastapi import Depends, Request

from backend.api.deps.infra import get_redis
from backend.api.deps.permissions import get_permission_service
from backend.api.deps.services import (
    get_feature_flag_service,
    get_knowledge_service,
    get_repo_analysis_service,
    get_task_service,
)
from backend.api.deps.uow import get_uow
from backend.application.chat.web_nonstream_workflow import ChatNonStreamWorkflow
from backend.application.chat.web_stream_workflow import ChatWorkflow
from backend.application.knowledge.upload_workflow import KnowledgeUploadWorkflow
from backend.application.repo_analysis.submit_workflow import RepoAnalysisSubmitWorkflow
from backend.contracts.interfaces import (
    AbstractTaskDispatcher,
    AbstractUnitOfWork,
)
from backend.infra.redis import redis_client
from backend.infra.task_dispatcher import TaskDispatcher
from backend.services.chat_service import SessionManager
from backend.services.feature_flag_service import FeatureFlagService
from backend.services.knowledge_service import KnowledgeService
from backend.services.permission_service import PermissionService
from backend.services.repo_analysis_service import RepoAnalysisService
from backend.services.task_service import TaskService


async def get_dispatcher(request: Request) -> TaskDispatcher:
    dispatcher = getattr(request.app.state, "_task_dispatcher", None)
    if dispatcher is None:
        taskiq_redis = await redis_client.get_taskiq_client()
        dispatcher = TaskDispatcher(taskiq_redis)
        request.app.state._task_dispatcher = dispatcher
    return dispatcher


def get_session_manager(
    uow: AbstractUnitOfWork = Depends(get_uow),
    permission_service: PermissionService = Depends(get_permission_service),
) -> SessionManager:
    return SessionManager(uow, permission_service)


def get_chat_workflow(
    uow: AbstractUnitOfWork = Depends(get_uow),
    dispatcher: AbstractTaskDispatcher = Depends(get_dispatcher),
    redis_client: redis.Redis = Depends(get_redis),
    permission_service: PermissionService = Depends(get_permission_service),
    feature_flag_service: FeatureFlagService = Depends(get_feature_flag_service),
    session_manager: SessionManager = Depends(get_session_manager),
) -> ChatWorkflow:
    return ChatWorkflow(
        uow,
        dispatcher,
        redis_client,
        permission_service,
        feature_flag_service,
        session_manager,
    )


def get_chat_nonstream_workflow(
    uow: AbstractUnitOfWork = Depends(get_uow),
    dispatcher: AbstractTaskDispatcher = Depends(get_dispatcher),
    redis_client: redis.Redis = Depends(get_redis),
    permission_service: PermissionService = Depends(get_permission_service),
    feature_flag_service: FeatureFlagService = Depends(get_feature_flag_service),
    session_manager: SessionManager = Depends(get_session_manager),
) -> ChatNonStreamWorkflow:
    return ChatNonStreamWorkflow(
        uow,
        dispatcher,
        redis_client,
        permission_service,
        feature_flag_service,
        session_manager,
    )


def get_knowledge_upload_workflow(
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    task_service: TaskService = Depends(get_task_service),
    dispatcher: AbstractTaskDispatcher = Depends(get_dispatcher),
) -> KnowledgeUploadWorkflow:
    return KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
        dispatcher=dispatcher,
    )


def get_repo_analysis_submit_workflow(
    repo_analysis_service: RepoAnalysisService = Depends(get_repo_analysis_service),
    task_service: TaskService = Depends(get_task_service),
    dispatcher: AbstractTaskDispatcher = Depends(get_dispatcher),
) -> RepoAnalysisSubmitWorkflow:
    return RepoAnalysisSubmitWorkflow(
        repo_analysis_service=repo_analysis_service,
        task_service=task_service,
        dispatcher=dispatcher,
    )
