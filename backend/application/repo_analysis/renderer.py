"""Markdown renderer for repo credibility reports."""

from backend.models.schemas.repo_analysis_schema import (
    README_ONLY_CAVEAT,
    ReadmeCredibilityAssessment,
    RepoEvidenceBundle,
)


class RepoReportRenderer:
    def render_markdown(
        self,
        *,
        subject: dict,
        snapshot: dict,
        evidence: RepoEvidenceBundle,
        assessment: ReadmeCredibilityAssessment,
        generated_by: str,
    ) -> str:
        lines = [
            f"# {assessment.project_name} README 可信度初筛报告",
            "",
            f"> {README_ONLY_CAVEAT}",
            "",
            "## 分析流程",
            "",
            "```mermaid",
            "flowchart LR",
            "  A[GitHub URL] --> B[Fetch README]",
            "  B --> C[Extract Evidence]",
            "  C --> D[Structured Assessment]",
            "  D --> E[Markdown Report]",
            "```",
            "",
            "## 总体判断",
            "",
            f"- 仓库：[{subject['owner']}/{subject['repo']}]({subject['url']})",
            f"- 项目类型：`{assessment.likely_project_type}`",
            f"- 包装/夸大风险：`{assessment.hype_risk}`",
            f"- 证据强度：`{assessment.evidence_strength}`",
            f"- 生成方式：`{generated_by}`",
            "",
            assessment.non_technical_verdict,
            "",
            "## 一句话摘要",
            "",
            assessment.one_sentence_summary,
            "",
            "## README 声称能力",
            "",
        ]
        if assessment.claimed_capabilities:
            for capability in assessment.claimed_capabilities:
                lines.append(
                    f"- **{capability.claim}**：置信度 `{capability.confidence}`"
                )
        else:
            lines.append("- 未提取到明确能力声明。")

        lines.extend(["", "## 关键发现", ""])
        if assessment.findings:
            for finding in assessment.findings:
                refs = ", ".join(f"`{ref}`" for ref in finding.evidence_refs) or "无"
                lines.extend(
                    [
                        f"### {finding.title}",
                        "",
                        f"- 严重性：`{finding.severity}`",
                        f"- 证据：{refs}",
                        "",
                        finding.non_technical_explanation,
                        "",
                    ]
                )
        else:
            lines.append("- 暂无关键发现。")

        lines.extend(["", "## 可信信号", ""])
        lines.extend(_bullet_list(assessment.credibility_signals))
        lines.extend(["", "## 缺失信号", ""])
        lines.extend(_bullet_list(assessment.missing_signals))
        lines.extend(["", "## 下一步建议问题", ""])
        lines.extend(_bullet_list(assessment.recommended_next_questions))
        lines.extend(["", "## GitHub 元信息", ""])
        lines.extend(
            [
                f"- 默认分支：`{snapshot.get('default_branch') or 'unknown'}`",
                f"- README SHA：`{snapshot.get('readme_sha') or 'unknown'}`",
                f"- Stars：`{snapshot.get('stars', 0)}`",
                f"- Forks：`{snapshot.get('forks', 0)}`",
                f"- License：`{snapshot.get('license') or 'unknown'}`",
            ]
        )

        lines.extend(["", "## Evidence Index", ""])
        for item in (
            evidence.readme_claims
            + evidence.metadata_signals
            + evidence.missing_signals
        ):
            lines.append(f"- `{item.id}` [{item.kind}] {item.detail}")

        return "\n".join(lines).rstrip() + "\n"


def _bullet_list(items: list[str]) -> list[str]:
    if not items:
        return ["- 暂无。"]
    return [f"- {item}" for item in items]
