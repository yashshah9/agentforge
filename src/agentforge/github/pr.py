"""Draft PR publishing — GitHub when configured, local placeholder otherwise."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

_REPO_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True, slots=True)
class DraftPRResult:
    url: str
    mode: str  # "github" | "local"
    number: int | None = None
    branch: str | None = None
    repo: str | None = None


class DraftPRPublisher(Protocol):
    def publish(
        self,
        *,
        run_id: str,
        issue: str,
        patch_summary: str,
        workspace: Path,
        repo_url: str,
    ) -> DraftPRResult: ...


def parse_github_repo(repo_url: str) -> tuple[str, str] | None:
    match = _REPO_RE.match(repo_url.strip())
    if not match:
        return None
    return match.group("owner"), match.group("repo")


class LocalDraftPRPublisher:
    """Used in tests and when GitHub credentials are not configured."""

    def publish(
        self,
        *,
        run_id: str,
        issue: str,
        patch_summary: str,
        workspace: Path,
        repo_url: str,
    ) -> DraftPRResult:
        del issue, patch_summary, workspace, repo_url
        return DraftPRResult(url=f"local://draft-pr/{run_id}", mode="local")


class GitHubDraftPRPublisher:
    """Create a branch + commit workspace files + open a *draft* pull request.

    Auth: fine-grained/classic PAT or pre-minted GitHub App installation token
    via ``token``. The control plane never sends the token into the sandbox.
    """

    def __init__(
        self,
        token: str,
        *,
        mirror_repo: str | None = None,
        base_branch: str = "main",
        api_base: str = "https://api.github.com",
        timeout: float = 60.0,
    ) -> None:
        self._mirror_repo = mirror_repo
        self._base_branch = base_branch
        self._client = httpx.Client(
            base_url=api_base.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def publish(
        self,
        *,
        run_id: str,
        issue: str,
        patch_summary: str,
        workspace: Path,
        repo_url: str,
    ) -> DraftPRResult:
        owner_repo = self._resolve_repo(repo_url)
        if owner_repo is None:
            raise RuntimeError(
                "GitHub publisher requires repo_url like https://github.com/owner/repo "
                "or AGENTFORGE_GITHUB_MIRROR_REPO=owner/repo for fixture:// runs"
            )
        owner, repo = owner_repo
        branch = f"agentforge/{run_id[:8]}"
        base_sha = self._ref_sha(owner, repo, self._base_branch)
        commit_sha = self._commit_workspace(
            owner=owner,
            repo=repo,
            workspace=workspace,
            base_sha=base_sha,
            message=f"agentforge: {patch_summary}",
        )
        self._create_or_update_ref(owner, repo, branch, commit_sha)
        pr = self._create_draft_pr(
            owner=owner,
            repo=repo,
            branch=branch,
            title=f"[agentforge] {issue[:72]}",
            body=_pr_body(run_id=run_id, issue=issue, patch_summary=patch_summary),
        )
        return DraftPRResult(
            url=str(pr["html_url"]),
            mode="github",
            number=int(pr["number"]),
            branch=branch,
            repo=f"{owner}/{repo}",
        )

    def _resolve_repo(self, repo_url: str) -> tuple[str, str] | None:
        parsed = parse_github_repo(repo_url)
        if parsed is not None:
            return parsed
        if self._mirror_repo and "/" in self._mirror_repo:
            owner, repo = self._mirror_repo.split("/", 1)
            return owner, repo
        return None

    def _ref_sha(self, owner: str, repo: str, branch: str) -> str:
        resp = self._client.get(f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
        if resp.status_code == 404:
            repo_resp = self._client.get(f"/repos/{owner}/{repo}")
            self._raise(repo_resp)
            default_branch = str(repo_resp.json()["default_branch"])
            resp = self._client.get(f"/repos/{owner}/{repo}/git/ref/heads/{default_branch}")
        self._raise(resp)
        return str(resp.json()["object"]["sha"])

    def _commit_workspace(
        self,
        *,
        owner: str,
        repo: str,
        workspace: Path,
        base_sha: str,
        message: str,
    ) -> str:
        base_commit = self._client.get(f"/repos/{owner}/{repo}/git/commits/{base_sha}")
        self._raise(base_commit)
        base_tree = str(base_commit.json()["tree"]["sha"])

        tree_items: list[dict[str, str]] = []
        for path in sorted(workspace.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(workspace)).replace("\\", "/")
            content = path.read_bytes()
            blob = self._client.post(
                f"/repos/{owner}/{repo}/git/blobs",
                json={
                    "content": base64.b64encode(content).decode("ascii"),
                    "encoding": "base64",
                },
            )
            self._raise(blob)
            tree_items.append(
                {
                    "path": rel,
                    "mode": "100644",
                    "type": "blob",
                    "sha": str(blob.json()["sha"]),
                }
            )

        tree = self._client.post(
            f"/repos/{owner}/{repo}/git/trees",
            json={"base_tree": base_tree, "tree": tree_items},
        )
        self._raise(tree)
        commit = self._client.post(
            f"/repos/{owner}/{repo}/git/commits",
            json={
                "message": message,
                "tree": tree.json()["sha"],
                "parents": [base_sha],
            },
        )
        self._raise(commit)
        return str(commit.json()["sha"])

    def _create_or_update_ref(self, owner: str, repo: str, branch: str, sha: str) -> None:
        ref = f"refs/heads/{branch}"
        create = self._client.post(
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": ref, "sha": sha},
        )
        if create.status_code in (200, 201):
            return
        if create.status_code == 422:
            update = self._client.patch(
                f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
                json={"sha": sha, "force": True},
            )
            self._raise(update)
            return
        self._raise(create)

    def _create_draft_pr(
        self,
        *,
        owner: str,
        repo: str,
        branch: str,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        resp = self._client.post(
            f"/repos/{owner}/{repo}/pulls",
            json={
                "title": title,
                "head": branch,
                "base": self._base_branch,
                "body": body,
                "draft": True,
            },
        )
        self._raise(resp)
        return dict(resp.json())

    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        raise RuntimeError(f"GitHub API {resp.status_code}: {resp.text[:500]}")


def _pr_body(*, run_id: str, issue: str, patch_summary: str) -> str:
    return (
        "## agentforge draft\n\n"
        f"**Run:** `{run_id}`\n\n"
        f"**Issue:** {issue}\n\n"
        f"**Patch:** {patch_summary}\n\n"
        "This PR was opened as a **draft**. Human approval in agentforge is required "
        "before merge.\n"
    )


def build_publisher(settings: Any) -> DraftPRPublisher:
    token = (getattr(settings, "github_token", "") or "").strip()
    if token:
        return GitHubDraftPRPublisher(
            token=token,
            mirror_repo=(getattr(settings, "github_mirror_repo", None) or None) or None,
            base_branch=getattr(settings, "github_base_branch", "main") or "main",
            api_base=getattr(settings, "github_api_base", "https://api.github.com"),
        )
    return LocalDraftPRPublisher()
