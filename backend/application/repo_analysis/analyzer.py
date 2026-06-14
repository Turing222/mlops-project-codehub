"""Pydantic AI analyzer for README-only repo credibility reports."""

import logging
from typing import Literal

from backend.ai.providers.llm.pydantic_ai_models import create_pydantic_ai_model
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.models.schemas.repo_analysis_schema import (
    README_ONLY_CAVEAT,
    ClaimedCapability,
    CredibilityFinding,
    ReadmeCredibilityAssessment,
    RepoEvidenceBundle,
)

logger = logging.getLogger(__name__)

_INSTRUCTIONS = """你是面向非技术人的 AI 开源项目可信度初筛分析员。
你只能基于用户提供的 README 摘要、GitHub metadata 和 evidence 判断。
不要声称你审计了完整代码、测试覆盖率或依赖实现。
输出要克制、可解释，所有 finding 尽量引用 evidence_refs。
最终输出必须是符合指定 schema 的 JSON object。
"""


class RepoCredibilityAnalyzer:
    def __init__(self, *, provider: str | None = None) -> None:
        self.provider = provider
        self._agent = None

    async def analyze(
        self,
        *,
        subject: dict,
        snapshot: dict,
        evidence: RepoEvidenceBundle,
    ) -> tuple[ReadmeCredibilityAssessment, Literal["pydantic_ai", "fallback"]]:
        try:
            return await self._run_pydantic_ai(
                subject=subject,
                snapshot=snapshot,
                evidence=evidence,
            ), "pydantic_ai"
        except Exception as exc:
            logger.warning("Repo credibility analyzer fallback: %s", exc)
            return self._fallback_assessment(
                subject=subject,
                evidence=evidence,
            ), "fallback"

    async def _run_pydantic_ai(
        self,
        *,
        subject: dict,
        snapshot: dict,
        evidence: RepoEvidenceBundle,
    ) -> ReadmeCredibilityAssessment:
        agent = self._ensure_agent()
        prompt = (
            "请基于以下结构化信息生成 README-only 项目可信度初筛。\n\n"
            f"SUBJECT:\n{subject}\n\n"
            f"SNAPSHOT:\n{snapshot}\n\n"
            f"EVIDENCE:\n{evidence.model_dump(mode='json')}\n"
        )
        result = await agent.run(prompt)
        output = result.output
        if isinstance(output, ReadmeCredibilityAssessment):
            return output
        return ReadmeCredibilityAssessment.model_validate(output)

    def _ensure_agent(self):
        if self._agent is None:
            try:
                from pydantic_ai import Agent, PromptedOutput
            except ImportError as exc:
                raise RuntimeError("pydantic-ai 未安装") from exc

            profile = get_llm_model_config().resolve_profile(
                self.provider or ai_settings.LLM_PROVIDER
            )
            self._agent = Agent(
                create_pydantic_ai_model(
                    profile=profile,
                    api_key=profile.resolve_api_key(),
                ),
                output_type=PromptedOutput(ReadmeCredibilityAssessment),
                instructions=_INSTRUCTIONS,
                instrument=True,
                name="repo_readme_credibility_analyzer",
            )
        return self._agent

    @staticmethod
    def _fallback_assessment(
        *,
        subject: dict,
        evidence: RepoEvidenceBundle,
    ) -> ReadmeCredibilityAssessment:
        missing = [item.detail for item in evidence.missing_signals]
        signals = [item.detail for item in evidence.metadata_signals]
        claims = [
            ClaimedCapability(
                claim=item.detail[:220],
                evidence_text=item.detail[:500],
                confidence="medium",
            )
            for item in evidence.readme_claims[:5]
        ]
        findings = [
            CredibilityFinding(
                title="README-only 初筛已生成，但 LLM 分析降级",
                severity="neutral",
                non_technical_explanation=(
                    "系统保留了 README 和仓库元信息证据，但本次未能完成模型增强判断。"
                ),
                evidence_refs=[item.id for item in evidence.readme_claims[:3]],
            )
        ]
        if missing:
            findings.append(
                CredibilityFinding(
                    title="README 缺少部分工程化说明",
                    severity="warning",
                    non_technical_explanation=(
                        "缺失测试、部署、CI 或评测说明会降低非技术人判断项目可靠性的信心。"
                    ),
                    evidence_refs=[item.id for item in evidence.missing_signals[:4]],
                )
            )
        return ReadmeCredibilityAssessment(
            project_name=str(subject.get("repo") or "unknown"),
            one_sentence_summary="基于 README 和 GitHub 元信息生成的项目初筛报告。",
            likely_project_type="unclear",
            non_technical_verdict=(
                "当前只能确认 README 中的公开描述，尚不足以判断完整代码水平或生产可用性。"
            ),
            hype_risk="unknown",
            evidence_strength="weak" if missing else "moderate",
            claimed_capabilities=claims,
            credibility_signals=signals[:8],
            missing_signals=missing[:8],
            recommended_next_questions=[
                "是否有可运行 demo 或部署文档？",
                "是否有测试、CI 和评测结果？",
                "核心能力是原创实现还是主要组合现有框架？",
            ],
            findings=findings,
            caveat=README_ONLY_CAVEAT,
        )
