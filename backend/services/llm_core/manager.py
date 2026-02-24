"""
Prompt Manager — 动态 Prompt 组装与上下文窗口管理 (Jinja2 版)

核心职责：
1. 使用 Jinja2 渲染 System Prompt（支持变量注入）
2. 按 [System] + [History] + [User Query] 顺序组装消息列表
3. 计算 Token 总量，超限时从最早历史开始逐轮丢弃
4. 返回组装结果与统计摘要
"""

import logging
from dataclasses import dataclass, field

from jinja2 import Template

from backend.core.config import settings
from backend.core.exceptions import TokenLimitExceeded
from backend.services.llm_core.templates import (
    DEFAULT_SYSTEM_TEMPLATE,
    render_system_prompt,
)
from backend.services.llm_core.tokens import count_messages_tokens

logger = logging.getLogger(__name__)


@dataclass
class AssembledPrompt:
    """Prompt 组装结果"""

    messages: list[dict] = field(default_factory=list)
    total_tokens: int = 0
    history_rounds_used: int = 0
    truncated: bool = False


class PromptManager:
    """
    Prompt 组装器 (Jinja2 驱动)

    使用方式：
        # 默认模板
        manager = PromptManager()
        result = manager.assemble(history, current_query)

        # 自定义模板变量（如注入用户名）
        manager = PromptManager(template_vars={"user_name": "Alice"})
        result = manager.assemble(history, current_query)

        # RAG 场景：使用 RAG 模板 + 注入检索到的文档片段
        from backend.services.llm_core.templates import RAG_SYSTEM_TEMPLATE
        manager = PromptManager(
            system_template=RAG_SYSTEM_TEMPLATE,
            template_vars={"context_chunks": ["片段1", "片段2"]},
        )
        result = manager.assemble(history, current_query)
    """

    def __init__(
        self,
        system_template: Template | None = None,
        template_vars: dict | None = None,
        max_context_tokens: int | None = None,
        max_history_rounds: int | None = None,
        reserved_response_tokens: int | None = None,
        model_name: str | None = None,
    ):
        self.system_template = system_template or DEFAULT_SYSTEM_TEMPLATE
        self.template_vars = template_vars or {}
        self.max_context_tokens = max_context_tokens or settings.LLM_MAX_CONTEXT_TOKENS
        self.max_history_rounds = max_history_rounds or settings.LLM_MAX_HISTORY_ROUNDS
        self.reserved_response_tokens = (
            reserved_response_tokens or settings.LLM_RESERVED_RESPONSE_TOKENS
        )
        self.model_name = model_name or settings.LLM_MODEL_NAME

    def assemble(
        self,
        history: list[dict],
        current_query: str,
        extra_vars: dict | None = None,
    ) -> AssembledPrompt:
        """
        组装完整的消息列表

        Args:
            history: 历史消息列表，格式 [{"role": "user", "content": "..."},
                     {"role": "assistant", "content": "..."}, ...]
            current_query: 当前用户的问题
            extra_vars: 可选，追加的模板变量（会与 self.template_vars 合并）

        Returns:
            AssembledPrompt 包含最终消息列表和统计信息

        Raises:
            TokenLimitExceeded: 即使无历史记录，System + Query 也超过上下文限制
        """
        token_budget = self.max_context_tokens - self.reserved_response_tokens

        # 1. 使用 Jinja2 渲染 System Prompt
        merged_vars = {**self.template_vars, **(extra_vars or {})}
        system_content = render_system_prompt(
            template=self.system_template, **merged_vars
        )

        # 2. 构建基础消息（System + 当前 Query）
        base_messages = []
        if system_content.strip():
            base_messages.append({"role": "system", "content": system_content})
        user_message = {"role": "user", "content": current_query}

        # 3. 计算基础 Token 消耗
        base_tokens = count_messages_tokens(
            base_messages + [user_message], self.model_name
        )

        if base_tokens > token_budget:
            raise TokenLimitExceeded(
                "System Prompt + 当前问题已超出 Token 限制",
                details={
                    "base_tokens": base_tokens,
                    "token_budget": token_budget,
                    "max_context_tokens": self.max_context_tokens,
                },
            )

        # 4. 将历史消息按轮次分组（一轮 = user + assistant）
        rounds = self._group_into_rounds(history)

        # 5. 限制最大历史轮数
        if len(rounds) > self.max_history_rounds:
            rounds = rounds[-self.max_history_rounds :]

        # 6. 逐轮添加，超限则截断（从最新往最旧，确保近期对话优先保留）
        remaining_budget = token_budget - base_tokens
        selected_rounds: list[list[dict]] = []
        truncated = False

        for round_msgs in reversed(rounds):
            round_tokens = count_messages_tokens(round_msgs, self.model_name)
            if round_tokens <= remaining_budget:
                selected_rounds.insert(0, round_msgs)
                remaining_budget -= round_tokens
            else:
                truncated = True
                break

        # 7. 组装最终消息列表
        final_messages = list(base_messages)
        for round_msgs in selected_rounds:
            final_messages.extend(round_msgs)
        final_messages.append(user_message)

        total_tokens = count_messages_tokens(final_messages, self.model_name)

        result = AssembledPrompt(
            messages=final_messages,
            total_tokens=total_tokens,
            history_rounds_used=len(selected_rounds),
            truncated=truncated,
        )

        logger.info(
            "Prompt 组装完成: total_tokens=%d, history_rounds=%d/%d, truncated=%s",
            result.total_tokens,
            result.history_rounds_used,
            len(rounds),
            result.truncated,
        )

        return result

    @staticmethod
    def _group_into_rounds(history: list[dict]) -> list[list[dict]]:
        """
        将扁平的消息列表分组为对话轮次

        每一轮通常是 [user_msg, assistant_msg]，
        但也兼容连续的同角色消息。

        Args:
            history: 按时间正序排列的历史消息列表

        Returns:
            分组后的轮次列表
        """
        if not history:
            return []

        rounds: list[list[dict]] = []
        current_round: list[dict] = []

        for msg in history:
            role = msg.get("role", "")
            if role == "system":
                # 跳过历史中的 system 消息（我们会注入自己的）
                continue
            if role == "user" and current_round:
                # 遇到新的 user 消息，说明上一轮结束
                rounds.append(current_round)
                current_round = []
            current_round.append(msg)

        if current_round:
            rounds.append(current_round)

        return rounds
