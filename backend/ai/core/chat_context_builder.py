import logging
import uuid
from dataclasses import dataclass

from backend.ai.core.prompt_manager import AssembledPrompt, PromptManager
from backend.ai.core.prompt_templates import RAG_SYSTEM_TEMPLATE
from backend.core.config import settings
from backend.domain.interfaces import AbstractRAGService

logger = logging.getLogger(__name__)


@dataclass
class PreparedChatContext:
    assembled_prompt: AssembledPrompt
    search_context: dict | None


class ChatContextBuilder:
    """构建对话上下文：记忆压缩 + RAG 检索 + Prompt 组装。"""

    def __init__(
        self,
        prompt_manager: PromptManager | None = None,
        rag_prompt_manager: PromptManager | None = None,
        rag_service: AbstractRAGService | None = None,
    ):
        self.prompt_manager = prompt_manager or PromptManager()
        self.rag_prompt_manager = rag_prompt_manager or PromptManager(
            system_template=RAG_SYSTEM_TEMPLATE
        )
        self.rag_service = rag_service

    async def build(
        self,
        history_messages,
        current_query: str,
        kb_id: uuid.UUID | None,
    ) -> PreparedChatContext:
        history_dicts = self._history_to_dicts(history_messages)
        memory_history, memory_summary = self._prepare_memory_context(
            history_dicts,
            current_query,
        )
        rag_chunks = await self._retrieve_rag_chunks(query_text=current_query, kb_id=kb_id)
        search_context = self._build_search_context(kb_id=kb_id, rag_chunks=rag_chunks)

        if rag_chunks:
            assembled = self.rag_prompt_manager.assemble(
                memory_history,
                current_query,
                extra_vars={
                    "context_chunks": [chunk["content"] for chunk in rag_chunks],
                    "conversation_summary": memory_summary,
                },
            )
        else:
            assembled = self.prompt_manager.assemble(
                memory_history,
                current_query,
                extra_vars={"conversation_summary": memory_summary},
            )

        return PreparedChatContext(
            assembled_prompt=assembled,
            search_context=search_context,
        )

    @staticmethod
    def _history_to_dicts(messages) -> list[dict]:
        """将 ORM 消息对象转换为 PromptManager 所需的字典列表。"""
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
            uow = getattr(self.rag_service, "uow", None)
            if uow is None or getattr(uow, "_session", None) is not None:
                return await self.rag_service.retrieve(query_text=query_text, kb_id=kb_id)

            async with uow:
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
