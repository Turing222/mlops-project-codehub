"""Chat safety metadata helpers.

职责：统一生成对话安全护栏、回答结果和 badcase 飞轮候选元数据。
边界：本模块只做轻量规则判断和 JSON 结构构造，不查询数据库、不调用外部安全模型。

WARNING: This module implements a PLACEHOLDER-LEVEL rule-based content filter.
It is NOT a substitute for a real content safety model. It is trivially
bypassable via synonyms, paraphrasing, or character substitution. This
implementation exists for early-stage safety data collection and MUST be
replaced with an ML-based classifier before production deployment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from backend.services.safety_scanner import (
    SafetyCategory,
    SafetyScanner,
    SafetyScanResult,
)

SCHEMA_VERSION = 1
SAFETY_REFUSAL_MESSAGE = "抱歉，这个请求涉及安全或权限风险，暂时无法回答。"
INJECTION_REFUSAL_MESSAGE = (
    "抱歉，我无法处理包含指令覆盖或角色切换内容的请求。请用正常方式提问。"
)


class ResponseOutcome(StrEnum):
    ANSWERED = "answered"
    REFUSED = "refused"
    BLOCKED = "blocked"
    FAILED = "failed"


class GuardrailAction(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


class GuardrailReason(StrEnum):
    PERMISSION_OR_PRIVACY_RISK = "permission_or_privacy_risk"
    UNSAFE_OUTPUT = "unsafe_output"
    INJECTION_RISK = "injection_risk"
    SENSITIVE_DATA_DETECTED = "sensitive_data_detected"


class BadcaseSeverity(StrEnum):
    P0 = "p0"
    P1 = "p1"


class BadcaseReason(StrEnum):
    SHOULD_REFUSE_BUT_ANSWERED = "should_refuse_but_answered"
    PERMISSION_OR_PRIVACY_RISK = "permission_or_privacy_risk"
    EMPTY_RETRIEVAL_REFUSAL = "empty_retrieval_refusal"
    PLANNER_PREFLIGHT_REFUSAL = "planner_preflight_refusal"
    WRONG_OR_UNHELPFUL_ANSWER = "wrong_or_unhelpful_answer"
    SHOULD_ANSWER_BUT_REFUSED = "should_answer_but_refused"


@dataclass(frozen=True)
class GuardrailDecision:
    """轻量护栏判断结果。"""

    triggered: bool
    reason: str | None = None
    scan_result: SafetyScanResult | None = None


def build_safety_metadata(
    *,
    response_outcome: ResponseOutcome,
    input_decision: GuardrailDecision | None = None,
    output_decision: GuardrailDecision | None = None,
    original_unsafe_output: str | None = None,
    badcase_severity: BadcaseSeverity | None = None,
    badcase_reason: BadcaseReason | None = None,
) -> dict[str, object]:
    input_triggered = bool(input_decision and input_decision.triggered)
    output_triggered = bool(output_decision and output_decision.triggered)
    is_badcase = badcase_severity is not None and badcase_reason is not None
    return {
        "schema_version": SCHEMA_VERSION,
        "response_outcome": response_outcome.value,
        "guardrail": {
            "input": {
                "triggered": input_triggered,
                "action": (
                    GuardrailAction.BLOCK.value
                    if input_triggered
                    else GuardrailAction.ALLOW.value
                ),
                "reason": input_decision.reason if input_decision else None,
            },
            "output": {
                "triggered": output_triggered,
                "action": (
                    GuardrailAction.BLOCK.value
                    if output_triggered
                    else GuardrailAction.ALLOW.value
                ),
                "reason": output_decision.reason if output_decision else None,
                "original_unsafe_output": original_unsafe_output,
            },
        },
        "badcase": {
            "is_badcase": is_badcase,
            "severity": badcase_severity.value if badcase_severity else None,
            "reason": badcase_reason.value if badcase_reason else None,
            "source": "auto",
            "status": "open",
        },
    }


def evaluate_input_guardrail(query_text: str) -> GuardrailDecision:
    """Evaluate input guardrail with safety scanner integration."""
    lowered = query_text.lower()

    # --- Phase 1: existing intent+target check ---
    _intent_en = re.compile(
        r"\b(?:leak|exfiltrat|bypass|circulvent|dump|hack|crack"
        r"|steal|sniff|scrape|extract)\b"
    )
    _target_en = re.compile(
        r"\b(?:password|token|api[-\s]?key|secret|credential"
        r"|id[-\s]?number|phone|idcard|ssn|social[-\s]security"
        r"|credit[-\s]?card|cvv|pin[-\s]?code)\b"
    )

    risky_intent_cn = (
        "泄露",
        "窃取",
        "绕过权限",
        "导出隐私",
        "入侵",
        "盗取",
        "非法获取",
        "私自导出",
        "越权",
        "脱库",
    )
    risky_target_cn = (
        "密码",
        "token",
        "api key",
        "密钥",
        "身份证",
        "手机号",
        "银行卡",
        "验证码",
        "支付密码",
        "登录密码",
    )

    has_intent = bool(_intent_en.search(lowered)) or any(
        kw in lowered for kw in risky_intent_cn
    )
    has_target = bool(_target_en.search(lowered)) or any(
        kw in lowered for kw in risky_target_cn
    )

    if has_intent and has_target:
        return GuardrailDecision(True, GuardrailReason.PERMISSION_OR_PRIVACY_RISK.value)

    # --- Phase 2: safety scanner ---
    scan_result = SafetyScanner.scan(query_text)

    if scan_result.category == SafetyCategory.INJECTION_RISK:
        return GuardrailDecision(
            True, GuardrailReason.INJECTION_RISK.value, scan_result
        )

    if scan_result.category == SafetyCategory.SENSITIVE_DATA_DETECTED:
        if SafetyScanner.has_secret_patterns(scan_result):
            return GuardrailDecision(
                True,
                GuardrailReason.SENSITIVE_DATA_DETECTED.value,
                scan_result,
            )
        # phone/email only: allow through but carry scan_result for log redaction
        return GuardrailDecision(False, scan_result=scan_result)

    return GuardrailDecision(False)


def evaluate_output_guardrail(content: str) -> GuardrailDecision:
    """Evaluate output guardrail (PLACEHOLDER — see module docstring)."""
    lowered = content.lower()

    _marker_en = re.compile(
        r"\b(?:password\s+is|token\s+is|api[-\s]?key\s+is"
        r"|secret\s+is|credential[-\s:]+|ssn[-\s:])\b"
    )
    risky_marker_cn = (
        "密码是",
        "token 是",
        "api key 是",
        "密钥是",
        "身份证号是",
        "验证码是",
    )

    if _marker_en.search(lowered) or any(kw in lowered for kw in risky_marker_cn):
        return GuardrailDecision(True, GuardrailReason.UNSAFE_OUTPUT.value)
    return GuardrailDecision(False)


def build_rag_refusal_metadata() -> dict[str, object]:
    return build_safety_metadata(
        response_outcome=ResponseOutcome.REFUSED,
        badcase_severity=BadcaseSeverity.P1,
        badcase_reason=BadcaseReason.EMPTY_RETRIEVAL_REFUSAL,
    )


def build_planner_refusal_metadata() -> dict[str, object]:
    return build_safety_metadata(
        response_outcome=ResponseOutcome.REFUSED,
        badcase_severity=BadcaseSeverity.P1,
        badcase_reason=BadcaseReason.PLANNER_PREFLIGHT_REFUSAL,
    )


def build_guardrail_success_metadata(
    *,
    output_decision: GuardrailDecision,
    original_content: str,
) -> dict[str, object]:
    if not output_decision.triggered:
        return build_safety_metadata(response_outcome=ResponseOutcome.ANSWERED)
    return build_safety_metadata(
        response_outcome=ResponseOutcome.REFUSED,
        output_decision=output_decision,
        original_unsafe_output=original_content,
        badcase_severity=BadcaseSeverity.P0,
        badcase_reason=BadcaseReason.SHOULD_REFUSE_BUT_ANSWERED,
    )
