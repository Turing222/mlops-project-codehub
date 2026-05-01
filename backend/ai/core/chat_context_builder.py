"""Chat context builder.

职责：合并短期对话记忆、RAG 检索结果和 Prompt 组装结果。
边界：本模块不调用 LLM，也不写入会话消息；只为 workflow 准备输入上下文。
副作用：会触发 RAG 检索并记录 trace 属性。
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from backend.ai.core.prompt_manager import AssembledPrompt, PromptManager
from backend.config.settings import settings
from backend.contracts.interfaces import AbstractRAGService
from backend.models.schemas.chat_schema import ConversationMessage
from backend.observability.trace_utils import set_span_attributes, trace_span

logger = logging.getLogger(__name__)


@dataclass
class PreparedChatContext:
    """对话上下文组装后的结果。"""

    assembled_prompt: AssembledPrompt
    search_context: dict | None


@dataclass
class PreparedRAGReferences:
    """RAG 片段和前端可展示检索上下文。"""

    context_chunks: list[str]
    search_context: dict | None


class ChatContextBuilder:
    """为聊天 workflow 准备 Prompt 和检索上下文。"""

    def __init__(
        self,
        prompt_manager: PromptManager | None = None,
        rag_prompt_manager: PromptManager | None = None,
        rag_service: AbstractRAGService | None = None,
    ):
        self.prompt_manager = prompt_manager or PromptManager()
        self.rag_prompt_manager = rag_prompt_manager or PromptManager(
            template_name="rag_system"
        )
        self.rag_service = rag_service

    async def build(
        self,
        history_messages,
        current_query: str,
        kb_id: uuid.UUID | None,
    ) -> PreparedChatContext:
        with trace_span(
            "chat.context.build",
            {
                "chat.kb_id": kb_id,
                "chat.query.char_count": len(current_query),
            },
        ) as span:
            history_dicts = self._history_to_dicts(history_messages)
            memory_history, memory_summary = self._prepare_memory_context(
                history_dicts,
                current_query,
            )
            rag_chunks = await self._retrieve_rag_chunks(
                query_text=current_query,
                kb_id=kb_id,
            )

            if rag_chunks:
                rag_references = self._build_rag_references(
                    kb_id=kb_id,
                    query_text=current_query,
                    rag_chunks=rag_chunks,
                )
                assembled = self.rag_prompt_manager.assemble(
                    memory_history,
                    current_query,
                    extra_vars={
                        "context_chunks": rag_references.context_chunks,
                        "conversation_summary": memory_summary,
                    },
                )
                search_context = rag_references.search_context
            else:
                search_context = None
                assembled = self.prompt_manager.assemble(
                    memory_history,
                    current_query,
                    extra_vars={"conversation_summary": memory_summary},
                )

            set_span_attributes(
                span,
                {
                    "chat.history.message_count": len(history_dicts),
                    "chat.memory.message_count": len(memory_history),
                    "chat.memory.summary_char_count": len(memory_summary),
                    "rag.hit_count": len(rag_chunks),
                    "chat.prompt.uses_rag": bool(rag_chunks),
                    "chat.prompt.message_count": len(assembled.messages),
                    "chat.prompt.tokens_input": assembled.total_tokens,
                },
            )
            return PreparedChatContext(
                assembled_prompt=assembled,
                search_context=search_context,
            )

    @staticmethod
    def _history_to_dicts(messages) -> list[ConversationMessage]:
        """只保留 Prompt 需要的用户/助手消息。"""
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
            with trace_span(
                "chat.context.retrieve_rag",
                {
                    "rag.kb_id": kb_id,
                    "rag.query.char_count": len(query_text),
                },
            ) as span:
                uow = getattr(self.rag_service, "uow", None)
                if uow is None or getattr(uow, "_session", None) is not None:
                    chunks = await self.rag_service.retrieve(
                        query_text=query_text,
                        kb_id=kb_id,
                    )
                else:
                    async with uow:
                        chunks = await self.rag_service.retrieve(
                            query_text=query_text,
                            kb_id=kb_id,
                        )
                set_span_attributes(span, {"rag.hit_count": len(chunks)})
                return chunks
        except Exception as exc:
            logger.warning("RAG 检索失败，降级为普通对话: %s", exc)
            return []

    @staticmethod
    def _build_search_context(
        kb_id: uuid.UUID | None,
        query_text: str,
        rag_chunks: list[dict],
    ) -> dict | None:
        return ChatContextBuilder._build_rag_references(
            kb_id=kb_id,
            query_text=query_text,
            rag_chunks=rag_chunks,
        ).search_context

    @staticmethod
    def _build_rag_references(
        kb_id: uuid.UUID | None,
        query_text: str,
        rag_chunks: list[dict],
    ) -> PreparedRAGReferences:
        if not rag_chunks:
            return PreparedRAGReferences(context_chunks=[], search_context=None)

        groups: list[dict[str, Any]] = []
        group_indexes: dict[tuple[str | None, str | None, str | None], int] = {}
        context_chunks: list[str] = []
        flat_chunks: list[dict[str, Any]] = []
        scores = [float(chunk.get("score", 0.0) or 0.0) for chunk in rag_chunks]

        for chunk in rag_chunks:
            source_type = chunk.get("source_type")
            file_id = chunk.get("file_id")
            message_id = chunk.get("message_id")
            key = (source_type, file_id, message_id)
            group_index = group_indexes.get(key)
            if group_index is None:
                group_index = len(groups)
                group_indexes[key] = group_index
                groups.append(
                    {
                        "ref_id": f"R{group_index + 1}",
                        "source_type": source_type,
                        "file_id": file_id,
                        "message_id": message_id,
                        "filename": chunk.get("filename"),
                        "chunks": [],
                    }
                )

            group = groups[group_index]
            chunk_ref_index = len(group["chunks"]) + 1
            ref_id = f"{group['ref_id']}.{chunk_ref_index}"
            chunk_index = chunk.get("chunk_index")
            chunk_ref = {
                "ref_id": ref_id,
                "chunk_id": chunk["id"],
                "chunk_index": chunk_index,
                "score": chunk.get("score"),
                "distance": chunk.get("distance"),
                "meta_info": chunk.get("meta_info") or {},
            }
            group["chunks"].append(chunk_ref)
            flat_chunks.append(
                {
                    "ref_id": ref_id,
                    "id": chunk["id"],
                    "score": chunk.get("score"),
                    "distance": chunk.get("distance"),
                    "source_type": source_type,
                    "file_id": file_id,
                    "message_id": message_id,
                    "chunk_index": chunk_index,
                }
            )
            context_chunks.append(
                ChatContextBuilder._format_context_chunk(ref_id=ref_id, chunk=chunk)
            )

        search_context = {
            "version": 1,
            "kb_id": str(kb_id) if kb_id else None,
            "query": query_text,
            "retrieval": {
                "hit_count": len(rag_chunks),
                "source_count": len(groups),
                "max_score": max(scores) if scores else 0.0,
                "avg_score": sum(scores) / len(scores) if scores else 0.0,
            },
            "refs": groups,
            "chunks": flat_chunks,
        }
        return PreparedRAGReferences(
            context_chunks=context_chunks,
            search_context=search_context,
        )

    @staticmethod
    def _format_context_chunk(ref_id: str, chunk: dict) -> str:
        source_label = (
            chunk.get("filename")
            or chunk.get("file_id")
            or chunk.get("message_id")
            or "unknown"
        )
        details = [f"来源：{source_label}"]
        chunk_index = chunk.get("chunk_index")
        if chunk_index is not None:
            details.append(f"chunk {chunk_index}")
        meta_info = chunk.get("meta_info") or {}
        page_label = meta_info.get("page_label") or meta_info.get("page")
        if page_label:
            details.append(f"页码：{page_label}")
        return f"[{ref_id}] {'，'.join(details)}\n{chunk['content']}"
