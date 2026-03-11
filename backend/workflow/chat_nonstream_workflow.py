import asyncio
import logging
import uuid

from langfuse import get_client, observe

from backend.ai.core import PromptManager
from backend.ai.core.prompt_templates import RAG_SYSTEM_TEMPLATE
from backend.core.config import settings
from backend.core.exceptions import ServiceError, ValidationError
from backend.core.redis import redis_client
from backend.domain.interfaces import AbstractLLMService, AbstractRAGService
from backend.models.orm.chat import MessageStatus
from backend.models.schemas.chat_schema import (
    ChatQueryResponse,
    LLMQueryDTO,
    MessageResponse,
)
from backend.services.chat_service import ChatMessageUpdater, SessionManager
from backend.services.unit_of_work import AbstractUnitOfWork

logger = logging.getLogger(__name__)


class ChatNonStreamWorkflow:
    """非流式对话编排器。"""

    _llm_semaphore: asyncio.Semaphore | None = None
    _db_semaphore: asyncio.Semaphore | None = None

    @classmethod
    def _get_llm_semaphore(cls) -> asyncio.Semaphore:
        if cls._llm_semaphore is None:
            cls._llm_semaphore = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)
        return cls._llm_semaphore

    @classmethod
    def _get_db_semaphore(cls) -> asyncio.Semaphore:
        if cls._db_semaphore is None:
            cls._db_semaphore = asyncio.Semaphore(settings.DB_MAX_CONCURRENCY)
        return cls._db_semaphore

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
        self.rag_prompt_manager = PromptManager(system_template=RAG_SYSTEM_TEMPLATE)
        self.rag_service = rag_service

    def _history_to_dicts(self, messages) -> list[dict]:
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
    def _group_history_rounds(history: list[dict]) -> list[list[dict]]:
        if not history:
            return []

        rounds: list[list[dict]] = []
        current_round: list[dict] = []
        for msg in history:
            role = msg.get("role", "")
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
        history: list[dict],
        current_query: str,
    ) -> list[dict]:
        if not history:
            return history

        latest = history[-1]
        if latest.get("role") != "user":
            return history

        latest_text = cls._normalize_text(latest.get("content", ""))
        query_text = cls._normalize_text(current_query)
        if latest_text and latest_text == query_text:
            return history[:-1]
        return history

    @classmethod
    def _build_rounds_summary(cls, rounds: list[list[dict]]) -> str:
        if not rounds:
            return ""

        snippet_limit = max(20, settings.CHAT_MEMORY_SNIPPET_CHARS)
        max_chars = max(1, settings.CHAT_MEMORY_SUMMARY_MAX_CHARS)
        lines: list[str] = []

        for round_msgs in rounds:
            user_text = cls._normalize_text(
                " ".join(
                    msg.get("content", "")
                    for msg in round_msgs
                    if msg.get("role") == "user"
                )
            )
            assistant_text = cls._normalize_text(
                " ".join(
                    msg.get("content", "")
                    for msg in round_msgs
                    if msg.get("role") == "assistant"
                )
            )
            if not user_text and not assistant_text:
                continue

            user_excerpt = cls._truncate_text(user_text, snippet_limit) or "(空)"
            assistant_excerpt = cls._truncate_text(assistant_text, snippet_limit) or "(空)"
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
        history: list[dict],
        current_query: str,
    ) -> tuple[list[dict], str]:
        history_without_current = cls._exclude_latest_query_from_history(
            history,
            current_query,
        )
        rounds = cls._group_history_rounds(history_without_current)
        recent_rounds = max(0, settings.CHAT_MEMORY_RECENT_ROUNDS)

        if recent_rounds <= 0:
            older_rounds = rounds
            kept_rounds: list[list[dict]] = []
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
            return await self.rag_service.retrieve(query_text=query_text, kb_id=kb_id)
        except Exception as exc:
            logger.warning("RAG 检索失败，降级为普通对话: %s", exc)
            return []

    @staticmethod
    def _build_search_context(
        kb_id: uuid.UUID | None,
        rag_chunks: list[dict],
    ) -> dict | None:
        if not rag_chunks:
            return None
        return {
            "kb_id": str(kb_id) if kb_id else None,
            "chunks": [
                {
                    "id": chunk["id"],
                    "score": chunk["score"],
                    "distance": chunk["distance"],
                    "source_type": chunk["source_type"],
                    "file_id": chunk["file_id"],
                    "message_id": chunk["message_id"],
                }
                for chunk in rag_chunks
            ],
        }

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

        if client_request_id:
            redis = await redis_client.init()
            lock_key = f"idempotency:chat:{client_request_id}"
            is_new = await redis.set(lock_key, "PROCESSING", nx=True, ex=300)
            if not is_new:
                val = await redis.get(lock_key)
                if val == "PROCESSING":
                    raise ServiceError(
                        "正在加速计算中...",
                        details={"client_request_id": client_request_id},
                    )
                async with self.uow:
                    msg = await self.uow.chat_repo.get_message_by_client_request_id(
                        client_request_id
                    )
                    if msg and msg.status == MessageStatus.SUCCESS:
                        session = await self.uow.chat_repo.get_session(msg.session_id)
                        return ChatQueryResponse(
                            session_id=session.id,
                            session_title=session.title,
                            answer=MessageResponse.model_validate(msg),
                        )

        async with self._get_db_semaphore():
            async with self.uow:
                user = await self.uow.users.get(user_id)
                if user and user.used_tokens >= user.max_tokens:
                    if client_request_id:
                        await redis.delete(lock_key)
                    raise ValidationError(
                        "Token 余额不足",
                        details={"used": user.used_tokens, "max": user.max_tokens},
                    )

                session_manager = SessionManager(self.uow)
                session = await session_manager.ensure_session(
                    user_id=user_id,
                    query_text=query_text,
                    session_id=session_id,
                    kb_id=kb_id,
                )
                await session_manager.create_user_message(
                    session_id=session.id,
                    content=query_text,
                )
                assistant_msg = await session_manager.create_assistant_message(
                    session_id=session.id,
                    client_request_id=client_request_id,
                )

        async with self._get_db_semaphore():
            async with self.uow:
                session_manager = SessionManager(self.uow)
                history_messages = await session_manager.get_session_messages(
                    session_id=session.id,
                    limit=settings.CHAT_MEMORY_FETCH_LIMIT,
                )

        history_dicts = self._history_to_dicts(history_messages)
        memory_history, memory_summary = self._prepare_memory_context(
            history_dicts,
            query_text,
        )
        rag_chunks = await self._retrieve_rag_chunks(query_text=query_text, kb_id=kb_id)
        search_context = self._build_search_context(kb_id=kb_id, rag_chunks=rag_chunks)
        if rag_chunks:
            assembled = self.rag_prompt_manager.assemble(
                memory_history,
                query_text,
                extra_vars={
                    "context_chunks": [chunk["content"] for chunk in rag_chunks],
                    "conversation_summary": memory_summary,
                },
            )
        else:
            assembled = self.prompt_manager.assemble(
                memory_history,
                query_text,
                extra_vars={"conversation_summary": memory_summary},
            )
        tokens_input = assembled.total_tokens

        llm_query = LLMQueryDTO(
            session_id=session.id,
            query_text=query_text,
            conversation_history=assembled.messages,
        )

        try:
            async with self._get_llm_semaphore():
                result = await self.llm_service.generate_response(llm_query)
        except Exception:
            if client_request_id:
                await redis.delete(lock_key)
            async with self._get_db_semaphore():
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(assistant_msg.id)
            raise

        if not result.success:
            if client_request_id:
                await redis.delete(lock_key)
            async with self._get_db_semaphore():
                async with self.uow:
                    updater = ChatMessageUpdater(self.uow)
                    await updater.update_as_failed(
                        assistant_msg.id,
                        error_content=result.error_message or "LLM 服务调用失败",
                    )
            raise ServiceError(
                "LLM 服务返回失败",
                details={"error": result.error_message},
            )

        async with self._get_db_semaphore():
            async with self.uow:
                updater = ChatMessageUpdater(self.uow)
                updated_msg = await updater.update_as_success(
                    message_id=assistant_msg.id,
                    content=result.content,
                    tokens_input=tokens_input,
                    tokens_output=result.completion_tokens,
                    search_context=search_context,
                )
                await self.uow.users.increment_used_tokens(
                    user_id,
                    tokens_input + (result.completion_tokens or 0),
                )

        if client_request_id:
            await redis.set(lock_key, str(updated_msg.id), ex=3600)

        return ChatQueryResponse(
            session_id=session.id,
            session_title=session.title,
            answer=MessageResponse.model_validate(updated_msg),
        )
