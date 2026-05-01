import asyncio
import logging
import uuid

from langfuse import get_client, observe

from backend.ai.core import PromptManager
from backend.ai.core.chat_context_builder import ChatContextBuilder
from backend.core.concurrency import (
    db_concurrency_slot,
    get_db_semaphore,
    get_llm_semaphore,
    llm_concurrency_slot,
)
from backend.core.config import settings
from backend.core.exceptions import (
    AppException,
    app_service_error,
    app_validation_error,
)
from backend.core.redis import redis_client
from backend.core.trace_utils import set_span_attributes, trace_span
from backend.domain.interfaces import (
    AbstractLLMService,
    AbstractRAGService,
    AbstractUnitOfWork,
)
from backend.models.orm.chat import MessageStatus
from backend.models.schemas.chat_schema import (
    ChatQueryResponse,
    ConversationMessage,
    LLMQueryDTO,
    MessageResponse,
)
from backend.services.chat_service import ChatMessageUpdater, SessionManager
from backend.services.knowledge_service import DEFAULT_KNOWLEDGE_BASE_NAME

logger = logging.getLogger(__name__)


class ChatNonStreamWorkflow:
    """非流式对话编排器。"""

    # R2/R4 修复：Semaphore 改为全局共享实例（见 core/concurrency.py），
    # 使用 threading.Lock 双重检查保护初始化，消除类级别竞态，
    # 并确保与 ChatWorkflow 共享同一并发上限。

    @staticmethod
    def _get_llm_semaphore() -> asyncio.Semaphore:
        return get_llm_semaphore()

    @staticmethod
    def _get_db_semaphore() -> asyncio.Semaphore:
        return get_db_semaphore()

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        llm_service: AbstractLLMService,
        prompt_manager: PromptManager | None = None,
        rag_service: AbstractRAGService | None = None,
    ):
        self.uow = uow
        self.llm_service = llm_service
        self.prompt_manager = prompt_manager or PromptManager()
        self.rag_prompt_manager = PromptManager(template_name="rag_system")
        self.rag_service = rag_service

    def _history_to_dicts(self, messages) -> list[ConversationMessage]:
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
            if msg.role in ("user", "assistant") and msg.content
        ]

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join((text or "").split())

    @staticmethod
    def _truncate_text(text: str, limit: int) -> str:
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        return f"{text[: max(0, limit - 3)]}..."

    @staticmethod
    def _group_history_rounds(
        history: list[ConversationMessage],
    ) -> list[list[ConversationMessage]]:
        if not history:
            return []

        rounds: list[list[ConversationMessage]] = []
        current_round: list[ConversationMessage] = []
        for msg in history:
            role = msg["role"]
            if role == "user" and current_round:
                rounds.append(current_round)
                current_round = []
            current_round.append(msg)

        if current_round:
            rounds.append(current_round)
        return rounds

    @classmethod
    def _exclude_latest_query_from_history(
        cls,
        history: list[ConversationMessage],
        current_query: str,
    ) -> list[ConversationMessage]:
        if not history:
            return history

        latest = history[-1]
        if latest["role"] != "user":
            return history

        latest_text = cls._normalize_text(latest["content"])
        query_text = cls._normalize_text(current_query)
        if latest_text and latest_text == query_text:
            return history[:-1]
        return history

    @classmethod
    def _build_rounds_summary(cls, rounds: list[list[ConversationMessage]]) -> str:
        if not rounds:
            return ""

        snippet_limit = max(20, settings.CHAT_MEMORY_SNIPPET_CHARS)
        max_chars = max(1, settings.CHAT_MEMORY_SUMMARY_MAX_CHARS)
        lines: list[str] = []

        for round_msgs in rounds:
            user_text = cls._normalize_text(
                " ".join(msg["content"] for msg in round_msgs if msg["role"] == "user")
            )
            assistant_text = cls._normalize_text(
                " ".join(
                    msg["content"] for msg in round_msgs if msg["role"] == "assistant"
                )
            )
            if not user_text and not assistant_text:
                continue

            user_excerpt = cls._truncate_text(user_text, snippet_limit) or "(空)"
            assistant_excerpt = (
                cls._truncate_text(assistant_text, snippet_limit) or "(空)"
            )
            lines.append(f"- 用户: {user_excerpt} | 助手: {assistant_excerpt}")

        if not lines:
            return ""

        original_lines = list(lines)
        while lines and len("\n".join(lines)) > max_chars:
            lines.pop(0)

        if not lines:
            return cls._truncate_text(original_lines[-1], max_chars)

        return "\n".join(lines)

    @classmethod
    def _prepare_memory_context(
        cls,
        history: list[ConversationMessage],
        current_query: str,
    ) -> tuple[list[ConversationMessage], str]:
        history_without_current = cls._exclude_latest_query_from_history(
            history,
            current_query,
        )
        rounds = cls._group_history_rounds(history_without_current)
        recent_rounds = max(0, settings.CHAT_MEMORY_RECENT_ROUNDS)

        if recent_rounds <= 0:
            older_rounds = rounds
            kept_rounds: list[list[ConversationMessage]] = []
        elif len(rounds) > recent_rounds:
            older_rounds = rounds[:-recent_rounds]
            kept_rounds = rounds[-recent_rounds:]
        else:
            older_rounds = []
            kept_rounds = rounds

        recent_history = [msg for round_msgs in kept_rounds for msg in round_msgs]
        summary_text = cls._build_rounds_summary(older_rounds)
        return recent_history, summary_text

    async def _retrieve_rag_chunks(
        self,
        query_text: str,
        kb_id: uuid.UUID | None,
    ) -> list[dict]:
        if not self.rag_service or kb_id is None:
            return []
        try:
            rag_uow = getattr(self.rag_service, "uow", None)
            if rag_uow is None or getattr(rag_uow, "_session", None) is not None:
                return await self.rag_service.retrieve(
                    query_text=query_text, kb_id=kb_id
                )

            async with db_concurrency_slot({"rag.kb_id": kb_id}):
                async with rag_uow:
                    return await self.rag_service.retrieve(
                        query_text=query_text,
                        kb_id=kb_id,
                    )
        except AppException:
            raise
        except Exception as exc:
            logger.warning("RAG 检索失败，降级为普通对话: %s", exc)
            return []

    @observe()
    async def handle_query(
        self,
        user_id: uuid.UUID,
        query_text: str,
        session_id: uuid.UUID | None = None,
        kb_id: uuid.UUID | None = None,
        client_request_id: str | None = None,
    ) -> ChatQueryResponse:
        get_client().update_current_trace(
            user_id=str(user_id),
            session_id=str(session_id) if session_id else None,
            tags=["chat_api", "non-stream"],
        )
        logger.info(
            "Workflow 收到查询: user_id=%s, session_id=%s, query_len=%d",
            user_id,
            session_id,
            len(query_text),
        )

        redis = None
        lock_key: str | None = None
        trace_attrs = {
            "chat.user_id": user_id,
            "chat.session_id": session_id,
            "chat.kb_id": kb_id,
            "chat.client_request_id.present": client_request_id is not None,
            "chat.query.char_count": len(query_text),
            "chat.stream": False,
        }

        with trace_span("chat.nonstream.idempotency_check", trace_attrs) as span:
            if client_request_id:
                redis = await redis_client.init()
                lock_key = f"idempotency:chat:{user_id}:{client_request_id}"
                is_new = await redis.set(lock_key, "PROCESSING", nx=True, ex=300)
                set_span_attributes(span, {"chat.idempotency.is_new": bool(is_new)})
                if not is_new:
                    val = await redis.get(lock_key)
                    set_span_attributes(span, {"chat.idempotency.value": val})
                    if val == "PROCESSING":
                        raise app_service_error(
                            "正在加速计算中...",
                            code="CHAT_REQUEST_PROCESSING",
                            details={"client_request_id": client_request_id},
                        )
                    async with self.uow:
                        msg = await self.uow.chat_repo.get_message_by_client_request_id(
                            client_request_id,
                            user_id,
                        )
                        if msg and msg.status == MessageStatus.SUCCESS:
                            session = await self.uow.chat_repo.get_session(
                                msg.session_id
                            )
                            if session is None:
                                raise app_service_error(
                                    "会话不存在",
                                    code="CHAT_SESSION_NOT_FOUND",
                                )
                            set_span_attributes(
                                span,
                                {"chat.idempotency.cached_message": True},
                            )
                            return ChatQueryResponse(
                                session_id=session.id,
                                session_title=session.title,
                                answer=MessageResponse.model_validate(msg),
                            )

        with trace_span(
            "chat.nonstream.create_session_and_messages", trace_attrs
        ) as span:
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    # R1/R5 修复：用 SELECT FOR UPDATE 悲观锁读取用户行，
                    # 防止多个并发请求同时通过余额检查（TOCTOU 竞态）
                    user = await self.uow.user_repo.get_with_lock(user_id)
                    if user and user.used_tokens >= user.max_tokens:
                        if redis is not None and lock_key is not None:
                            await redis.delete(lock_key)
                        raise app_validation_error(
                            "Token 余额不足",
                            code="TOKEN_QUOTA_EXCEEDED",
                            details={"used": user.used_tokens, "max": user.max_tokens},
                        )

                    session_manager = SessionManager(self.uow)
                    resolved_kb_id = kb_id
                    if session_id is None and resolved_kb_id is None:
                        default_kb = (
                            await self.uow.knowledge_repo.get_kb_by_name_for_user(
                                name=DEFAULT_KNOWLEDGE_BASE_NAME,
                                user_id=user_id,
                            )
                        )
                        if default_kb is not None:
                            resolved_kb_id = default_kb.id

                    session = await session_manager.ensure_session(
                        user_id=user_id,
                        query_text=query_text,
                        session_id=session_id,
                        kb_id=resolved_kb_id,
                    )
                    effective_kb_id = kb_id or session.kb_id
                    await session_manager.create_user_message(
                        session_id=session.id,
                        content=query_text,
                        user_id=user_id,
                    )
                    assistant_msg = await session_manager.create_assistant_message(
                        session_id=session.id,
                        client_request_id=client_request_id,
                        user_id=user_id,
                    )
            set_span_attributes(
                span,
                {
                    "chat.session_id": session.id,
                    "chat.assistant_message_id": assistant_msg.id,
                },
            )
            trace_attrs["chat.session_id"] = session.id
            trace_attrs["chat.assistant_message_id"] = assistant_msg.id

        with trace_span("chat.nonstream.fetch_history", trace_attrs) as span:
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    session_manager = SessionManager(self.uow)
                    history_messages = await session_manager.get_session_messages(
                        session_id=session.id,
                        limit=settings.CHAT_MEMORY_FETCH_LIMIT,
                    )
            set_span_attributes(
                span, {"chat.history.message_count": len(history_messages)}
            )

        with trace_span("chat.nonstream.prepare_context", trace_attrs) as span:
            history_dicts = self._history_to_dicts(history_messages)
            memory_history, memory_summary = self._prepare_memory_context(
                history_dicts,
                query_text,
            )
            rag_chunks = await self._retrieve_rag_chunks(
                query_text=query_text,
                kb_id=effective_kb_id,
            )
            if rag_chunks:
                rag_references = ChatContextBuilder._build_rag_references(
                    kb_id=effective_kb_id,
                    query_text=query_text,
                    rag_chunks=rag_chunks,
                )
                search_context = rag_references.search_context
                assembled = self.rag_prompt_manager.assemble(
                    memory_history,
                    query_text,
                    extra_vars={
                        "context_chunks": rag_references.context_chunks,
                        "conversation_summary": memory_summary,
                    },
                )
            else:
                search_context = None
                assembled = self.prompt_manager.assemble(
                    memory_history,
                    query_text,
                    extra_vars={"conversation_summary": memory_summary},
                )
            tokens_input = assembled.total_tokens
            set_span_attributes(
                span,
                {
                    "chat.history.message_count": len(history_dicts),
                    "chat.memory.message_count": len(memory_history),
                    "chat.memory.summary_char_count": len(memory_summary),
                    "chat.prompt.tokens_input": tokens_input,
                    "chat.prompt.message_count": len(assembled.messages),
                    "chat.prompt.uses_rag": bool(rag_chunks),
                    "rag.hit_count": len(rag_chunks),
                },
            )

        llm_query = LLMQueryDTO(
            session_id=session.id,
            query_text=query_text,
            conversation_history=assembled.messages,
        )

        try:
            with trace_span("chat.nonstream.call_llm", trace_attrs) as span:
                async with llm_concurrency_slot(trace_attrs):
                    result = await self.llm_service.generate_response(llm_query)
                set_span_attributes(
                    span,
                    {
                        "llm.success": result.success,
                        "llm.latency_ms": result.latency_ms,
                        "llm.response.completion_tokens": result.completion_tokens,
                        "llm.response.char_count": len(result.content),
                    },
                )
        except AppException:
            if redis is not None and lock_key is not None:
                await redis.delete(lock_key)
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(assistant_msg.id)
            raise
        except Exception as exc:
            if redis is not None and lock_key is not None:
                await redis.delete(lock_key)
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(assistant_msg.id)
            raise app_service_error(
                "LLM 服务调用失败，请稍后重试",
                code="LLM_SERVICE_ERROR",
            ) from exc

        if not result.success:
            if redis is not None and lock_key is not None:
                await redis.delete(lock_key)
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(
                        assistant_msg.id,
                        error_content=result.error_message or "LLM 服务调用失败",
                    )
            raise app_service_error(
                "LLM 服务返回失败",
                code="LLM_SERVICE_FAILED",
                details={"error": result.error_message},
            )

        with trace_span("chat.nonstream.persist_answer", trace_attrs) as span:
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    updated_msg = await updater.update_as_success(
                        message_id=assistant_msg.id,
                        content=result.content,
                        tokens_input=tokens_input,
                        tokens_output=result.completion_tokens,
                        search_context=search_context,
                    )
                    # R1/R5 修复：条件原子累加，超出上限时返回 False
                    total_tokens = tokens_input + (result.completion_tokens or 0)
                    ok = await self.uow.user_repo.increment_used_tokens_guarded(
                        user_id, total_tokens
                    )
                    if not ok:
                        logger.warning(
                            "Token 累加后超出上限，本次消耗未记录: user_id=%s, delta=%d",
                            user_id,
                            total_tokens,
                        )
            set_span_attributes(
                span,
                {
                    "chat.tokens_input": tokens_input,
                    "chat.tokens_output": result.completion_tokens,
                },
            )

        if redis is not None and lock_key is not None:
            await redis.set(lock_key, str(updated_msg.id), ex=3600)

        return ChatQueryResponse(
            session_id=session.id,
            session_title=session.title,
            answer=MessageResponse.model_validate(updated_msg),
        )
