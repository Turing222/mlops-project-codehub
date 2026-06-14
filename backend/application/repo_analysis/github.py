"""GitHub README-only repo collector.

职责：通过 GitHub REST API 读取 public repo metadata 和 README。
边界：不解析业务证据、不调用 LLM、不访问 GitHub 网页 HTML。
"""

import base64
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from backend.core.exceptions import app_bad_request, app_not_found, app_service_error

GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_REPO_URL = "https://github.com/{owner}/{repo}"


@dataclass(frozen=True)
class ParsedGitHubRepo:
    owner: str
    repo: str
    url: str


@dataclass(frozen=True)
class GitHubRepoSnapshot:
    subject: dict
    snapshot: dict
    readme_text: str


def parse_github_repo_url(repo_url: str) -> ParsedGitHubRepo:
    parsed = urlparse(repo_url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise app_bad_request("仅支持 GitHub 仓库 URL", code="INVALID_GITHUB_URL")

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise app_bad_request(
            "GitHub URL 必须包含 owner/repo", code="INVALID_GITHUB_URL"
        )

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise app_bad_request(
            "GitHub URL 必须包含 owner/repo", code="INVALID_GITHUB_URL"
        )

    return ParsedGitHubRepo(
        owner=owner,
        repo=repo,
        url=GITHUB_REPO_URL.format(owner=owner, repo=repo),
    )


class GitHubRepoCollector:
    def __init__(
        self,
        *,
        api_base_url: str = GITHUB_API_BASE_URL,
        timeout_seconds: float = 20.0,
        token: str | None = None,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.token = token if token is not None else os.getenv("GITHUB_TOKEN")

    async def collect(self, repo: ParsedGitHubRepo) -> GitHubRepoSnapshot:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "dewflow-repo-analysis",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        async with httpx.AsyncClient(
            base_url=self.api_base_url,
            timeout=self.timeout_seconds,
            headers=headers,
            trust_env=False,
        ) as client:
            repo_payload = await self._get_json(
                client, f"/repos/{repo.owner}/{repo.repo}"
            )
            readme_payload = await self._get_json(
                client, f"/repos/{repo.owner}/{repo.repo}/readme"
            )

        readme_text = self._decode_readme(readme_payload)
        subject = {
            "provider": "github",
            "owner": repo.owner,
            "repo": repo.repo,
            "url": repo.url,
        }
        snapshot = {
            "default_branch": str(repo_payload.get("default_branch") or ""),
            "readme_sha": str(readme_payload.get("sha") or ""),
            "stars": int(repo_payload.get("stargazers_count") or 0),
            "forks": int(repo_payload.get("forks_count") or 0),
            "topics": list(repo_payload.get("topics") or []),
            "license": (repo_payload.get("license") or {}).get("spdx_id"),
            "repo_updated_at": repo_payload.get("updated_at"),
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        return GitHubRepoSnapshot(
            subject=subject,
            snapshot=snapshot,
            readme_text=readme_text,
        )

    async def _get_json(self, client: httpx.AsyncClient, path: str) -> dict:
        try:
            response = await client.get(path)
        except httpx.HTTPError as exc:
            raise app_service_error(
                "GitHub 请求失败，请稍后重试",
                code="GITHUB_REQUEST_FAILED",
            ) from exc

        if response.status_code == 404:
            raise app_not_found(
                "GitHub 仓库或 README 不存在", code="GITHUB_REPO_NOT_FOUND"
            )
        if response.status_code == 403:
            details = _github_error_details(response)
            raise app_service_error(
                "GitHub API 暂时不可用或达到访问限制",
                code="GITHUB_RATE_LIMITED",
                details=details,
            )
        if response.status_code >= 400:
            raise app_service_error(
                "GitHub API 返回错误",
                code="GITHUB_API_ERROR",
                details=_github_error_details(response),
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise app_service_error(
                "GitHub 响应格式无效", code="GITHUB_INVALID_RESPONSE"
            )
        return payload

    @staticmethod
    def _decode_readme(readme_payload: dict) -> str:
        content = readme_payload.get("content")
        encoding = readme_payload.get("encoding")
        if not isinstance(content, str) or encoding != "base64":
            raise app_not_found(
                "GitHub README 内容不可用", code="GITHUB_README_NOT_FOUND"
            )
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception as exc:
            raise app_service_error(
                "GitHub README 解码失败", code="GITHUB_README_DECODE_FAILED"
            ) from exc


def _github_error_details(response: httpx.Response) -> dict[str, object]:
    details: dict[str, object] = {
        "status_code": response.status_code,
        "rate_limit_remaining": response.headers.get("x-ratelimit-remaining"),
        "rate_limit_reset": response.headers.get("x-ratelimit-reset"),
    }
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        details["github_message"] = payload["message"]
    return details
