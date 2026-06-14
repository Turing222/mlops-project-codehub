"""Repository Protocol definitions.

职责：定义各 Repository 的抽象接口（structural typing via Protocol）。
边界：本模块仅声明方法签名，不含实现；方法签名引用 ORM 类型作为返回值，
      因此与 ORM 存在类型级耦合（运行时不依赖 ORM 实现）。
      contracts.interfaces.AbstractUnitOfWork 的属性类型引用本模块，
      不再依赖 backend.repositories.* 的具体类。
"""

import datetime
import uuid
from collections.abc import Collection, Sequence
from typing import Any, Protocol

from backend.models.enums import MessageStatus, WorkspaceRole
from backend.models.orm.access import UserWorkspaceRole, Workspace
from backend.models.orm.chat import ChatMessage, ChatSession
from backend.models.orm.chunk import DocumentChunk
from backend.models.orm.credits import CreditAccount, CreditTransaction, UsageRecord
from backend.models.orm.knowledge import File, FileStatus, FileVisibility, KnowledgeBase
from backend.models.orm.repo_analysis import RepoAnalysisResult, RepoAnalysisRun
from backend.models.orm.task import TaskJob, TaskStatus
from backend.models.orm.user import User
from backend.models.schemas.audit_schema import AuditEventFilters
from backend.models.schemas.chat.context_state import ContextState
from backend.models.schemas.user_schema import UserUpdate


class UserCreateData(Protocol):
    """Minimal structural type for user creation data."""

    username: str
    email: str
    hashed_password: str
    max_tokens: int


# ---------------------------------------------------------------------------
# Repository Protocols
# ---------------------------------------------------------------------------


class AccessRepositoryProtocol(Protocol):
    async def get_workspace_role(
        self, *, user_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> WorkspaceRole | None: ...

    async def get_workspace(self, workspace_id: uuid.UUID) -> Workspace | None: ...

    async def get_workspace_by_slug(self, slug: str) -> Workspace | None: ...

    async def create_workspace(
        self, *, name: str, slug: str, owner_id: uuid.UUID | None
    ) -> Workspace: ...

    async def update_workspace(
        self, *, workspace: Workspace, obj_in: dict[str, Any]
    ) -> Workspace: ...

    async def soft_delete_workspace(self, workspace: Workspace) -> None: ...

    async def delete_workspace(self, workspace: Workspace) -> None: ...

    async def add_workspace_role(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        role: WorkspaceRole,
    ) -> UserWorkspaceRole: ...

    async def get_workspace_member(
        self, *, user_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> UserWorkspaceRole | None: ...

    async def update_workspace_role(
        self, *, user_role: UserWorkspaceRole, role: WorkspaceRole
    ) -> UserWorkspaceRole: ...

    async def remove_workspace_member(self, user_role: UserWorkspaceRole) -> None: ...

    async def count_workspace_owners(self, *, workspace_id: uuid.UUID) -> int: ...

    async def list_workspace_members(
        self, *, workspace_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> Sequence[tuple[UserWorkspaceRole, User]]: ...

    async def count_workspace_members(self, *, workspace_id: uuid.UUID) -> int: ...

    async def list_workspaces_for_user(
        self, *, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> Sequence[tuple[Workspace, WorkspaceRole]]: ...

    async def count_workspaces_for_user(self, *, user_id: uuid.UUID) -> int: ...


class AuditRepositoryProtocol(Protocol):
    async def add(self, event: Any) -> None: ...

    async def count_events(self, filters: AuditEventFilters) -> int: ...

    async def list_events(
        self, *, filters: AuditEventFilters, skip: int, limit: int
    ) -> Sequence[Any]: ...


class ChatRepositoryProtocol(Protocol):
    async def get_session(self, session_id: uuid.UUID) -> ChatSession | None: ...

    async def get_context_state(self, session_id: uuid.UUID) -> ContextState: ...

    async def update_context_state_if_version_matches(
        self, *, session_id: uuid.UUID, expected_version: int, next_state: ContextState
    ) -> bool: ...

    async def create_session(
        self,
        user_id: uuid.UUID,
        title: str = "新对话",
        kb_id: uuid.UUID | None = None,
        workspace_id: uuid.UUID | None = None,
        llm_config: dict | None = None,
    ) -> ChatSession: ...

    async def get_user_sessions(
        self, user_id: uuid.UUID, skip: int = 0, limit: int = 20
    ) -> Sequence[ChatSession]: ...

    async def get_user_sessions_with_total_tokens(
        self, user_id: uuid.UUID, skip: int = 0, limit: int = 20
    ) -> list[tuple[ChatSession, int]]: ...

    async def count_user_sessions(self, user_id: uuid.UUID) -> int: ...

    async def get_session_total_tokens(self, session_id: uuid.UUID) -> int: ...

    async def count_session_messages(self, session_id: uuid.UUID) -> int: ...

    async def get_message(self, message_id: uuid.UUID) -> ChatMessage | None: ...

    async def create_message(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str,
        status: MessageStatus = MessageStatus.SUCCESS,
        latency_ms: int | None = None,
        tokens_input: int = 0,
        tokens_output: int = 0,
        client_request_id: str | None = None,
        search_context: dict | None = None,
        user_id: uuid.UUID | None = None,
        message_metadata: dict | None = None,
    ) -> ChatMessage: ...

    async def get_session_messages(
        self, session_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> Sequence[ChatMessage]: ...

    async def update_message_status(
        self,
        message_id: uuid.UUID,
        status: MessageStatus,
        content: str | None = None,
        latency_ms: int | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        search_context: dict | None = None,
        message_metadata: dict | None = None,
    ) -> ChatMessage | None: ...

    async def create_thinking_message(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str = "",
        user_id: uuid.UUID | None = None,
    ) -> ChatMessage: ...

    async def get_message_by_client_request_id(
        self, client_request_id: str, user_id: uuid.UUID
    ) -> ChatMessage | None: ...


class KnowledgeRepositoryProtocol(Protocol):
    async def get_kb(self, kb_id: uuid.UUID) -> KnowledgeBase | None: ...

    async def get_kb_for_user(
        self, kb_id: uuid.UUID, user_id: uuid.UUID
    ) -> KnowledgeBase | None: ...

    async def get_kb_by_name_for_user(
        self, *, name: str, user_id: uuid.UUID
    ) -> KnowledgeBase | None: ...

    async def create_kb(
        self,
        *,
        name: str,
        description: str | None,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> KnowledgeBase: ...

    async def create_file(
        self,
        kb_id: uuid.UUID,
        filename: str,
        file_path: str,
        file_size: int,
        status: FileStatus = FileStatus.UPLOADED,
        owner_id: uuid.UUID | None = None,
        workspace_id: uuid.UUID | None = None,
        visibility: FileVisibility = FileVisibility.WORKSPACE,
        storage_backend: str = "local",
        storage_bucket: str | None = None,
        storage_key: str | None = None,
        content_sha256: str | None = None,
    ) -> File: ...

    async def get_file(self, file_id: uuid.UUID) -> File | None: ...

    async def list_files_by_kb(self, kb_id: uuid.UUID) -> Sequence[File]: ...

    async def delete_file_record(self, file_id: uuid.UUID) -> None: ...

    async def get_file_by_hash_and_status(
        self, *, kb_id: uuid.UUID, content_sha256: str, status: FileStatus
    ) -> File | None: ...

    async def update_file_status(
        self, file_id: uuid.UUID, status: FileStatus
    ) -> File | None: ...

    async def try_transition_file_status(
        self,
        *,
        file_id: uuid.UUID,
        expected_previous_statuses: Collection[FileStatus],
        target_status: FileStatus,
    ) -> bool: ...

    async def mark_stale_ingestion_files_failed(
        self, *, older_than: datetime.datetime
    ) -> int: ...

    async def delete_chunks_for_file(self, file_id: uuid.UUID) -> None: ...

    async def add_chunks(self, chunks_data: list[dict]) -> None: ...

    async def vector_search(
        self, query_vector: list[float], limit: int = 5
    ) -> Sequence[DocumentChunk]: ...

    async def search_chunks_for_kb(
        self, query_vector: list[float], kb_id: uuid.UUID, limit: int = 5
    ) -> list[tuple[DocumentChunk, float]]: ...

    async def search_chunks_for_kb_fulltext(
        self, *, normalized_query: str, kb_id: uuid.UUID, limit: int = 5
    ) -> list[tuple[DocumentChunk, float]]: ...


class TaskRepositoryProtocol(Protocol):
    async def get(self, task_id: uuid.UUID) -> TaskJob | None: ...

    async def create(
        self,
        action_type: str,
        payload: dict,
        status: TaskStatus = TaskStatus.PENDING,
        progress: int = 0,
    ) -> TaskJob: ...

    async def update_status(
        self,
        task_id: uuid.UUID,
        status: TaskStatus,
        progress: int | None = None,
        error_log: str | None = None,
    ) -> TaskJob | None: ...

    async def get_by_status(
        self, status: TaskStatus, skip: int = 0, limit: int = 100
    ) -> Sequence[TaskJob]: ...

    async def get_user_tasks(
        self, user_id: uuid.UUID, skip: int = 0, limit: int = 20
    ) -> Sequence[TaskJob]: ...

    async def mark_completed(
        self, task_id: uuid.UUID, progress: int = 100
    ) -> TaskJob | None: ...

    async def mark_failed(
        self, task_id: uuid.UUID, error_log: str
    ) -> TaskJob | None: ...

    async def mark_processing(
        self, task_id: uuid.UUID, progress: int = 0
    ) -> TaskJob | None: ...

    async def mark_stale_kb_ingestion_tasks_failed(
        self, *, older_than: datetime.datetime, error_log: str
    ) -> int: ...


class RepoAnalysisRepositoryProtocol(Protocol):
    async def create_run(
        self,
        *,
        user_id: uuid.UUID,
        repo_url: str,
        owner: str,
        repo: str,
        rubric_version: str,
    ) -> RepoAnalysisRun: ...

    async def get_run(self, run_id: uuid.UUID) -> RepoAnalysisRun | None: ...

    async def get_run_for_user(
        self, *, run_id: uuid.UUID, user_id: uuid.UUID
    ) -> RepoAnalysisRun | None: ...

    async def set_task_id(
        self, *, run_id: uuid.UUID, task_id: uuid.UUID
    ) -> RepoAnalysisRun | None: ...

    async def mark_running(self, *, run_id: uuid.UUID) -> RepoAnalysisRun | None: ...

    async def mark_failed(
        self, *, run_id: uuid.UUID, error_message: str
    ) -> RepoAnalysisRun | None: ...

    async def mark_succeeded(self, *, run_id: uuid.UUID) -> RepoAnalysisRun | None: ...

    async def create_result(
        self,
        *,
        run_id: uuid.UUID,
        subject: dict[str, Any],
        snapshot: dict[str, Any],
        evidence: dict[str, Any],
        structured_report: dict[str, Any],
        markdown_report: str,
        generated_by: str,
    ) -> RepoAnalysisResult: ...

    async def get_result_for_run(
        self, run_id: uuid.UUID
    ) -> RepoAnalysisResult | None: ...


class UserRepositoryProtocol(Protocol):
    async def get(self, id: Any) -> User | None: ...

    async def get_multi(self, *, skip: int = 0, limit: int = 100) -> Sequence[User]: ...

    async def create(self, *, obj_in: Any) -> User: ...

    async def update(
        self, *, db_obj: User, obj_in: UserUpdate | dict[str, Any]
    ) -> User: ...

    async def remove(self, *, id: Any) -> User | None: ...

    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_username(self, username: str) -> User | None: ...

    async def get_by_phone(self, phone: str) -> User | None: ...

    async def get_by_google_sub(self, google_sub: str) -> User | None: ...

    async def get_existing_usernames(self, usernames: list[str]) -> set[str]: ...

    async def bulk_upsert(self, user_maps: list[dict[str, str]]) -> None: ...

    async def increment_used_tokens(self, user_id: uuid.UUID, amount: int) -> None: ...

    async def get_with_lock(self, user_id: uuid.UUID) -> User | None: ...

    async def try_increment_used_tokens_with_limit(
        self, user_id: uuid.UUID, amount: int
    ) -> bool: ...


class CreditRepositoryProtocol(Protocol):
    async def get_account(self, user_id: uuid.UUID) -> CreditAccount | None: ...

    async def get_account_with_lock(
        self, user_id: uuid.UUID
    ) -> CreditAccount | None: ...

    async def get_account_by_id_with_lock(
        self, account_id: uuid.UUID
    ) -> CreditAccount | None: ...

    async def create_account(self, user_id: uuid.UUID) -> CreditAccount: ...

    async def update_account_balance(
        self, account_id: uuid.UUID, balance: int
    ) -> None: ...

    async def try_decrement_balance(self, account_id: uuid.UUID, cost: int) -> bool: ...

    async def try_increment_balance(
        self, account_id: uuid.UUID, amount: int
    ) -> bool: ...

    async def add_transaction(
        self,
        *,
        account_id: uuid.UUID,
        amount: int,
        source: str,
        expires_at: datetime.datetime | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CreditTransaction: ...

    async def get_transaction_by_idempotency_key(
        self, idempotency_key: str
    ) -> CreditTransaction | None: ...

    async def create_usage_record(
        self,
        *,
        user_id: uuid.UUID,
        chat_message_id: uuid.UUID | None = None,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        credit_cost: int,
        metadata: dict[str, Any] | None = None,
    ) -> UsageRecord: ...

    async def get_usage_record_by_chat_message_id(
        self, chat_message_id: uuid.UUID
    ) -> UsageRecord | None: ...

    async def list_transactions(
        self,
        *,
        account_id: uuid.UUID,
        source: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[CreditTransaction]: ...

    async def count_transactions(
        self, account_id: uuid.UUID, source: str | None = None
    ) -> int: ...

    async def get_expired_grants_sum(
        self, account_id: uuid.UUID, now: datetime.datetime
    ) -> int: ...

    async def get_already_expired_sum(self, account_id: uuid.UUID) -> int: ...

    async def get_spent_sum(self, account_id: uuid.UUID) -> int: ...

    async def get_protected_positive_sum(
        self, account_id: uuid.UUID, now: datetime.datetime
    ) -> int: ...

    async def list_accounts_needing_expiration(
        self,
        now: datetime.datetime,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> Sequence[uuid.UUID]: ...
