"""Prompt manager.

职责：渲染 system prompt，按上下文预算组装 history 和当前问题。
边界：本模块不读取数据库、不调用 LLM；模板来源由 PromptResolver 负责。
失败处理：基础 prompt 超过 token 预算时直接抛出业务错误，避免继续请求模型。
"""

import logging
from dataclasses import dataclass, field

from jinja2 import Template

from backend.ai.core.prompt_resolver import get_prompt_resolver
from backend.ai.core.prompt_templates import (
    render_system_prompt,
)
from backend.ai.core.token_counter import count_messages_tokens
from backend.config.llm import get_llm_model_config
from backend.config.settings import settings
from backend.core.exceptions import app_payload_too_large
from backend.models.schemas.chat_schema import ConversationMessage

logger = logging.getLogger(__name__)


@dataclass
class AssembledPrompt:
    """Prompt 组装结果和预算统计。"""

    messages: list[ConversationMessage] = field(default_factory=list)
    total_tokens: int = 0
    history_rounds_used: int = 0
    truncated: bool = False


class PromptManager:
    """Jinja2 驱动的 Prompt 组装器。"""

    def __init__(
        self,
        system_template: Template | None = None,
        template_name: str = "default_system",
        template_vars: dict | None = None,
        max_context_tokens: int | None = None,
        max_history_rounds: int | None = None,
        reserved_response_tokens: int | None = None,
        model_name: str | None = None,
    ):
        self.system_template = system_template
        self.template_name = template_name
        self.template_vars = template_vars or {}
        self.max_context_tokens = max_context_tokens or settings.LLM_MAX_CONTEXT_TOKENS
        self.max_history_rounds = max_history_rounds or settings.LLM_MAX_HISTORY_ROUNDS
        self.reserved_response_tokens = (
            reserved_response_tokens or settings.LLM_RESERVED_RESPONSE_TOKENS
        )
        self.model_name = model_name or get_llm_model_config().resolve_profile().model

    def assemble(
        self,
        history: list[ConversationMessage],
        current_query: str,
        extra_vars: dict | None = None,
    ) -> AssembledPrompt:
        """组装模型输入；超预算时优先保留当前问题和最新历史。"""
        token_budget = self.max_context_tokens - self.reserved_response_tokens

        merged_vars = {**self.template_vars, **(extra_vars or {})}
        system_template = self.system_template or get_prompt_resolver().get_template(
            self.template_name
        )
        system_content = render_system_prompt(template=system_template, **merged_vars)

        base_messages: list[ConversationMessage] = []
        if system_content.strip():
            base_messages.append({"role": "system", "content": system_content})
        user_message: ConversationMessage = {"role": "user", "content": current_query}

        base_tokens = count_messages_tokens(
            base_messages + [user_message], self.model_name
        )

        if base_tokens > token_budget:
            raise app_payload_too_large(
                "System Prompt + 当前问题已超出 Token 限制",
                code="TOKEN_LIMIT_EXCEEDED",
                details={
                    "base_tokens": base_tokens,
                    "token_budget": token_budget,
                    "max_context_tokens": self.max_context_tokens,
                },
            )

        rounds = self._group_into_rounds(history)

        if len(rounds) > self.max_history_rounds:
            rounds = rounds[-self.max_history_rounds :]

        # 从最新轮次向前填充，避免早期历史挤掉当前上下文。
        remaining_budget = token_budget - base_tokens
        selected_rounds: list[list[ConversationMessage]] = []
        truncated = False

        for round_msgs in reversed(rounds):
            round_tokens = count_messages_tokens(round_msgs, self.model_name)
            if round_tokens <= remaining_budget:
                selected_rounds.insert(0, round_msgs)
                remaining_budget -= round_tokens
            else:
                truncated = True
                break

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
    def _group_into_rounds(
        history: list[ConversationMessage],
    ) -> list[list[ConversationMessage]]:
        """按 user 消息边界拆分历史，兼容连续同角色消息。"""
        if not history:
            return []

        rounds: list[list[ConversationMessage]] = []
        current_round: list[ConversationMessage] = []

        for msg in history:
            role = msg["role"]
            if role == "system":
                # workflow 会注入当前模板的 system prompt，历史 system 消息不参与预算。
                continue
            if role == "user" and current_round:
                rounds.append(current_round)
                current_round = []
            current_round.append(msg)

        if current_round:
            rounds.append(current_round)

        return rounds
