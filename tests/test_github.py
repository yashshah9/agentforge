"""GitHub draft PR publisher tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agentforge.github import LocalDraftPRPublisher, parse_github_repo
from agentforge.github.pr import GitHubDraftPRPublisher


def test_parse_github_repo() -> None:
    assert parse_github_repo("https://github.com/acme/demo") == ("acme", "demo")
    assert parse_github_repo("https://github.com/acme/demo.git") == ("acme", "demo")
    assert parse_github_repo("git@github.com:acme/demo.git") == ("acme", "demo")
    assert parse_github_repo("fixture://broken_counter") is None


def test_local_publisher(tmp_path: Path) -> None:
    result = LocalDraftPRPublisher().publish(
        run_id="abc",
        issue="fix",
        patch_summary="patched",
        workspace=tmp_path,
        repo_url="fixture://broken_counter",
    )
    assert result.mode == "local"
    assert result.url == "local://draft-pr/abc"


def test_github_publisher_happy_path(tmp_path: Path) -> None:
    (tmp_path / "counter.py").write_text("x = 1\n", encoding="utf-8")

    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "basesha"}})
        if "/git/commits/basesha" in path:
            return httpx.Response(200, json={"tree": {"sha": "treesha"}})
        if path.endswith("/git/blobs"):
            return httpx.Response(201, json={"sha": "blobsha"})
        if path.endswith("/git/trees"):
            return httpx.Response(201, json={"sha": "newtree"})
        if path.endswith("/git/commits") and request.method == "POST":
            return httpx.Response(201, json={"sha": "commitsha"})
        if path.endswith("/git/refs") and request.method == "POST":
            return httpx.Response(201, json={"ref": "refs/heads/agentforge/runid123"})
        if path.endswith("/pulls") and request.method == "POST":
            body = json.loads(request.content.decode())
            assert body["draft"] is True
            return httpx.Response(
                201,
                json={
                    "html_url": "https://github.com/acme/demo/pull/42",
                    "number": 42,
                },
            )
        return httpx.Response(404, json={"message": f"unexpected {request.method} {path}"})

    transport = httpx.MockTransport(handler)
    pub = GitHubDraftPRPublisher("token", mirror_repo="acme/demo", api_base="https://api.github.com")
    pub._client = httpx.Client(
        base_url="https://api.github.com",
        transport=transport,
        headers={"Authorization": "Bearer token"},
    )
    result = pub.publish(
        run_id="runid123456",
        issue="Fix bug",
        patch_summary="fixed",
        workspace=tmp_path,
        repo_url="fixture://broken_counter",
    )
    assert result.mode == "github"
    assert result.url == "https://github.com/acme/demo/pull/42"
    assert result.number == 42
    assert any(m == "POST" and p.endswith("/pulls") for m, p in calls)


def test_github_publisher_requires_repo(tmp_path: Path) -> None:
    pub = GitHubDraftPRPublisher("token")
    with pytest.raises(RuntimeError, match="GITHUB_MIRROR_REPO"):
        pub.publish(
            run_id="r1",
            issue="x",
            patch_summary="y",
            workspace=tmp_path,
            repo_url="fixture://broken_counter",
        )
