from functools import lru_cache

from fastapi import Depends

from backend.api.deps.permissions import get_permission_service
from backend.api.deps.uow import get_uow
from backend.config.settings import settings
from backend.config.web_settings import get_web_settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.infra.redis import redis_client
from backend.services.credit_service import CreditService
from backend.services.feature_flag_service import FeatureFlagService
from backend.services.google_oauth_service import GoogleOAuthService
from backend.services.knowledge_service import KnowledgeService
from backend.services.object_storage import ObjectStorage, create_object_storage
from backend.services.permission_service import PermissionService
from backend.services.repo_analysis_service import RepoAnalysisService
from backend.services.session_query_service import SessionQueryService
from backend.services.sms_service import SMSService
from backend.services.task_service import TaskService
from backend.services.user_import_service import UserImportService
from backend.services.user_service import UserService
from backend.services.workspace_service import WorkspaceService


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    """进程级单例：S3 client 有连接池，每次请求重建开销高。

    测试时可通过 get_object_storage.cache_clear() + app.dependency_overrides 重置。
    """
    return create_object_storage(settings)


def get_knowledge_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
    storage: ObjectStorage = Depends(get_object_storage),
    permission_service: PermissionService = Depends(get_permission_service),
) -> KnowledgeService:
    return KnowledgeService(
        uow=uow,
        storage=storage,
        max_upload_size_mb=settings.KNOWLEDGE_MAX_UPLOAD_SIZE_MB,
        permission_service=permission_service,
    )


def get_task_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> TaskService:
    return TaskService(uow=uow)


def get_session_query_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> SessionQueryService:
    return SessionQueryService(uow=uow)


def get_user_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> UserService:
    return UserService(uow=uow)


def get_user_import_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> UserImportService:
    return UserImportService(uow=uow)


def get_workspace_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
    permission_service: PermissionService = Depends(get_permission_service),
) -> WorkspaceService:
    return WorkspaceService(uow=uow, permission_service=permission_service)


def get_sms_service() -> SMSService:
    ws = get_web_settings()
    return SMSService(
        redis_client=redis_client,
        sms_code_expire_seconds=ws.SMS_CODE_EXPIRE_SECONDS,
        sms_code_rate_limit_seconds=ws.SMS_CODE_RATE_LIMIT_SECONDS,
        sms_mock_mode=ws.SMS_MOCK_MODE,
    )


def get_google_oauth_service() -> GoogleOAuthService:
    ws = get_web_settings()
    return GoogleOAuthService(
        google_oauth_enabled=ws.GOOGLE_OAUTH_ENABLED,
        google_client_id=ws.GOOGLE_CLIENT_ID,
        google_client_secret=ws.GOOGLE_CLIENT_SECRET,
        allowed_redirect_uris=ws.GOOGLE_ALLOWED_REDIRECT_URIS,
    )


def get_credit_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> CreditService:
    return CreditService(uow=uow)


def get_repo_analysis_service(
    uow: AbstractUnitOfWork = Depends(get_uow),
) -> RepoAnalysisService:
    return RepoAnalysisService(uow=uow)


@lru_cache(maxsize=1)
def get_feature_flag_service() -> FeatureFlagService:
    """进程级单例：FeatureFlagService 持有内存缓存，每次请求重建开销无意义。

    测试时可通过 get_feature_flag_service.cache_clear() + app.dependency_overrides 重置。
    """
    return FeatureFlagService(
        growthbook_api_host=settings.GROWTHBOOK_API_HOST,
        growthbook_sdk_key=settings.GROWTHBOOK_SDK_KEY,
        app_env=settings.APP_ENV,
        beta_user_email_whitelist={
            e.strip()
            for e in settings.BETA_USER_EMAIL_WHITELIST.split(",")
            if e.strip()
        },
        beta_user_phone_whitelist={
            p.strip()
            for p in settings.BETA_USER_PHONE_WHITELIST.split(",")
            if p.strip()
        },
    )
