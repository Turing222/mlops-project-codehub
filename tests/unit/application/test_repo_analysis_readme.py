"""Repo analysis README-only workflow unit tests.

职责：验证 GitHub URL 解析、证据提取和 Markdown 渲染；边界：不访问真实 GitHub、不调用 LLM。
"""

import pytest

from backend.application.repo_analysis.evidence import RepoEvidenceExtractor
from backend.application.repo_analysis.github import parse_github_repo_url
from backend.application.repo_analysis.renderer import RepoReportRenderer
from backend.core.exceptions import AppException
from backend.models.schemas.repo_analysis_schema import (
    README_ONLY_CAVEAT,
    ClaimedCapability,
    CredibilityFinding,
    ReadmeCredibilityAssessment,
)


def test_parse_github_repo_url_accepts_standard_url() -> None:
    parsed = parse_github_repo_url("https://github.com/openai/codex.git")

    assert parsed.owner == "openai"
    assert parsed.repo == "codex"
    assert parsed.url == "https://github.com/openai/codex"


def test_parse_github_repo_url_rejects_non_github() -> None:
    with pytest.raises(AppException, match="仅支持 GitHub"):
        parse_github_repo_url("https://example.com/openai/codex")


def test_evidence_extractor_builds_claims_and_missing_signals() -> None:
    evidence = RepoEvidenceExtractor().extract(
        readme_text=(
            "# Demo Agent\n\n"
            "This AI agent uses OpenAI and LangChain to run workflow automation.\n"
        ),
        snapshot={
            "stars": 12,
            "forks": 3,
            "license": "MIT",
            "topics": ["ai", "agent"],
        },
    )

    assert evidence.readme_claims
    assert evidence.readme_claims[0].id == "readme_claim_1"
    assert any(item.id == "metadata_license" for item in evidence.metadata_signals)
    assert any("测试" in item.detail for item in evidence.missing_signals)


def test_renderer_outputs_caveat_mermaid_and_evidence_refs() -> None:
    evidence = RepoEvidenceExtractor().extract(
        readme_text="Production-ready AI agent with OpenAI tools.",
        snapshot={"stars": 1, "forks": 0, "license": None, "topics": []},
    )
    assessment = ReadmeCredibilityAssessment(
        project_name="demo-agent",
        one_sentence_summary="一个 README-only 初筛样例。",
        likely_project_type="demo_wrapper",
        non_technical_verdict="README 声称较强，但工程证据不足。",
        hype_risk="medium",
        evidence_strength="weak",
        claimed_capabilities=[
            ClaimedCapability(
                claim="Production-ready AI agent",
                evidence_text="Production-ready AI agent",
                confidence="medium",
            )
        ],
        credibility_signals=["README 描述清楚"],
        missing_signals=["缺少测试说明"],
        recommended_next_questions=["是否有 CI？"],
        findings=[
            CredibilityFinding(
                title="支撑证据不足",
                severity="warning",
                non_technical_explanation="README 声称生产可用，但缺少测试和部署证据。",
                evidence_refs=["readme_claim_1", "missing_signal_1"],
            )
        ],
    )

    markdown = RepoReportRenderer().render_markdown(
        subject={
            "owner": "owner",
            "repo": "demo-agent",
            "url": "https://github.com/owner/demo-agent",
        },
        snapshot={
            "default_branch": "main",
            "readme_sha": "abc",
            "stars": 1,
            "forks": 0,
            "license": None,
        },
        evidence=evidence,
        assessment=assessment,
        generated_by="fallback",
    )

    assert README_ONLY_CAVEAT in markdown
    assert "```mermaid" in markdown
    assert "`readme_claim_1`" in markdown
    assert "`missing_signal_1`" in markdown
