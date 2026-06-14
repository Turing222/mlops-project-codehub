"""Repo analysis request/response schemas.

职责：定义 README-only GitHub 项目可信度初筛接口和结构化报告。
边界：不执行 GitHub 访问或 LLM 生成。
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

RepoAnalysisStatusValue = Literal["pending", "running", "succeeded", "failed"]
ProjectType = Literal[
    "demo_wrapper",
    "framework_assembly",
    "research_prototype",
    "product_candidate",
    "unclear",
]
RiskLevel = Literal["low", "medium", "high", "unknown"]
EvidenceStrength = Literal["weak", "moderate", "strong", "unknown"]
FindingSeverity = Literal["positive", "neutral", "warning", "risk"]

RUBRIC_VERSION_README_ONLY = "readme-only-v1"
README_ONLY_CAVEAT = "本报告仅基于 README 和公开仓库元信息，不代表完整代码审计。"


class RepoAnalysisSubmitRequest(BaseModel):
    repo_url: Annotated[str, Field(min_length=1, max_length=500)]

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class RepoAnalysisSubmitResponse(BaseModel):
    run_id: uuid.UUID
    task_id: uuid.UUID
    status: RepoAnalysisStatusValue


class RepoAnalysisRunPayload(BaseModel):
    id: uuid.UUID
    status: RepoAnalysisStatusValue
    repo_url: str
    owner: str
    repo: str
    task_id: uuid.UUID | None = None
    rubric_version: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class RepoSubject(BaseModel):
    provider: Literal["github"] = "github"
    owner: str
    repo: str
    url: str


class RepoSnapshot(BaseModel):
    default_branch: str
    readme_sha: str
    stars: int
    forks: int
    topics: list[str] = Field(default_factory=list)
    license: str | None = None
    repo_updated_at: str | None = None
    fetched_at: datetime


class EvidenceItem(BaseModel):
    id: str
    kind: str
    title: str
    detail: str
    source: str


class RepoEvidenceBundle(BaseModel):
    readme_excerpt: str
    readme_claims: list[EvidenceItem] = Field(default_factory=list)
    metadata_signals: list[EvidenceItem] = Field(default_factory=list)
    missing_signals: list[EvidenceItem] = Field(default_factory=list)


class ClaimedCapability(BaseModel):
    claim: str = Field(min_length=1, max_length=220)
    evidence_text: str | None = Field(default=None, max_length=500)
    confidence: Literal["low", "medium", "high"] = "medium"


class CredibilityFinding(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    severity: FindingSeverity
    non_technical_explanation: str = Field(min_length=1, max_length=800)
    evidence_refs: list[str] = Field(default_factory=list)


class ReadmeCredibilityAssessment(BaseModel):
    project_name: str = Field(min_length=1, max_length=160)
    one_sentence_summary: str = Field(min_length=1, max_length=400)
    likely_project_type: ProjectType
    non_technical_verdict: str = Field(min_length=1, max_length=800)
    hype_risk: RiskLevel
    evidence_strength: EvidenceStrength
    claimed_capabilities: list[ClaimedCapability] = Field(default_factory=list)
    credibility_signals: list[str] = Field(default_factory=list, max_length=10)
    missing_signals: list[str] = Field(default_factory=list, max_length=10)
    recommended_next_questions: list[str] = Field(default_factory=list, max_length=10)
    findings: list[CredibilityFinding] = Field(default_factory=list, max_length=12)
    caveat: str = README_ONLY_CAVEAT


class RepoReportPayload(BaseModel):
    structured: ReadmeCredibilityAssessment
    markdown: str
    generated_by: Literal["pydantic_ai", "fallback"]


class RepoAnalysisRunResponse(BaseModel):
    run: RepoAnalysisRunPayload
    subject: RepoSubject | None = None
    snapshot: RepoSnapshot | None = None
    evidence: RepoEvidenceBundle | None = None
    report: RepoReportPayload | None = None
