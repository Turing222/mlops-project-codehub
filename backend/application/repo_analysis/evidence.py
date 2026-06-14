"""README-only evidence extraction for repo analysis."""

import re

from backend.models.schemas.repo_analysis_schema import EvidenceItem, RepoEvidenceBundle

CLAIM_KEYWORDS = (
    "agent",
    "rag",
    "llm",
    "ai",
    "benchmark",
    "production",
    "eval",
    "workflow",
    "tool",
    "openai",
    "langchain",
    "llamaindex",
    "autogen",
    "crewai",
)


class RepoEvidenceExtractor:
    def extract(
        self,
        *,
        readme_text: str,
        snapshot: dict,
    ) -> RepoEvidenceBundle:
        lines = _interesting_lines(readme_text)
        claims = [
            EvidenceItem(
                id=f"readme_claim_{idx + 1}",
                kind="readme_claim",
                title="README 声称能力",
                detail=line,
                source="README",
            )
            for idx, line in enumerate(lines[:8])
        ]

        metadata = [
            EvidenceItem(
                id="metadata_stars",
                kind="metadata_signal",
                title="GitHub stars",
                detail=str(snapshot.get("stars", 0)),
                source="GitHub repo metadata",
            ),
            EvidenceItem(
                id="metadata_forks",
                kind="metadata_signal",
                title="GitHub forks",
                detail=str(snapshot.get("forks", 0)),
                source="GitHub repo metadata",
            ),
        ]
        if snapshot.get("license"):
            metadata.append(
                EvidenceItem(
                    id="metadata_license",
                    kind="metadata_signal",
                    title="License",
                    detail=str(snapshot["license"]),
                    source="GitHub repo metadata",
                )
            )
        topics = snapshot.get("topics") or []
        if topics:
            metadata.append(
                EvidenceItem(
                    id="metadata_topics",
                    kind="metadata_signal",
                    title="GitHub topics",
                    detail=", ".join(str(topic) for topic in topics[:12]),
                    source="GitHub repo metadata",
                )
            )

        missing = _missing_signals(readme_text)
        missing_items = [
            EvidenceItem(
                id=f"missing_signal_{idx + 1}",
                kind="missing_signal",
                title="README 缺失信号",
                detail=signal,
                source="README",
            )
            for idx, signal in enumerate(missing)
        ]

        return RepoEvidenceBundle(
            readme_excerpt=_readme_excerpt(readme_text),
            readme_claims=claims,
            metadata_signals=metadata,
            missing_signals=missing_items,
        )


def _interesting_lines(readme_text: str) -> list[str]:
    normalized_lines = []
    for raw_line in readme_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line.strip(" #\t"))
        if len(line) < 18:
            continue
        lowered = line.lower()
        if any(keyword in lowered for keyword in CLAIM_KEYWORDS):
            normalized_lines.append(line[:500])
    if normalized_lines:
        return normalized_lines
    return [
        re.sub(r"\s+", " ", line.strip(" #\t"))[:500]
        for line in readme_text.splitlines()
        if len(line.strip()) >= 40
    ][:5]


def _missing_signals(readme_text: str) -> list[str]:
    lowered = readme_text.lower()
    checks = [
        ("未在 README 中明显发现测试说明", ("test", "pytest", "vitest", "coverage")),
        ("未在 README 中明显发现 CI/CD 说明", ("ci", "github actions", "workflow")),
        ("未在 README 中明显发现部署说明", ("deploy", "docker", "kubernetes")),
        ("未在 README 中明显发现评测或 benchmark 复现说明", ("benchmark", "eval")),
    ]
    return [
        message for message, needles in checks if not any(n in lowered for n in needles)
    ]


def _readme_excerpt(readme_text: str) -> str:
    compact = re.sub(r"\n{3,}", "\n\n", readme_text.strip())
    return compact[:4000]
