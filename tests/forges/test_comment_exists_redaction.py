"""A comment posted with a known secret value (or a token-shaped string) in it is stored
redacted, and `comment_exists` still finds it from the original text: the duplicate-post
check compares what would be posted with what the host holds."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import COMMENT_MARKER, RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.local import LocalForge
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost
from tests.forges.github_host import GitHubHost, answer
from tests.forges.test_azure_landed_reads import top_level
from tests.redaction_fakes import SECRET, known

GITHUB = RepoId(forge="github", account="example", name="app")
AZURE = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
LOCAL = RepoId(forge="local", account="local", name="app")
BASE = "/repos/example/app"
TOKEN_SHAPED = "ghp_" + "a1B2c3D4" * 5
BODIES = {
    "a known value": f"the run printed {SECRET}\n{COMMENT_MARKER}",
    "a token shape": f"the run printed {TOKEN_SHAPED}\n{COMMENT_MARKER}",
}


@pytest.mark.parametrize("body", BODIES.values(), ids=BODIES)
def test_the_local_forge_finds_a_comment_it_kept_redacted(tmp_path: Path, body: str) -> None:
    forge = LocalForge(tmp_path)
    number = forge.create_pr(LOCAL, head="spec/x/1", base="main", title="t", body="b")

    with known():
        [posted] = forge.post_comment(LOCAL, number, body=body)
        found = forge.comment_exists(LOCAL, number, COMMENT_MARKER, body)

    assert found == posted


@pytest.mark.usefixtures("github_env")
@pytest.mark.parametrize("body", BODIES.values(), ids=BODIES)
def test_the_github_forge_finds_a_comment_the_host_holds_redacted(body: str) -> None:
    held: list[str] = []

    def post(request: httpx.Request) -> httpx.Response:
        held.append(json.loads(request.content)["body"])
        return answer({"id": 5, "node_id": "IC_5", "body": held[-1]}, 201)

    def listing(request: httpx.Request) -> httpx.Response:
        return answer([{"id": 5, "node_id": "IC_5", "body": text} for text in held])

    host = GitHubHost(
        routes={
            ("POST", f"{BASE}/issues/17/comments"): post,
            ("GET", f"{BASE}/issues/17/comments"): listing,
        }
    )

    with known():
        forge = GitHubForge(http=host)
        [posted] = forge.post_comment(GITHUB, 17, body=body)
        found = forge.comment_exists(GITHUB, 17, COMMENT_MARKER, body)

    assert SECRET not in held[0]
    assert TOKEN_SHAPED not in held[0]
    assert found == posted == "IC_5"


@pytest.mark.usefixtures("rest_env")
def test_the_azure_forge_finds_a_comment_the_host_holds_redacted() -> None:
    body = BODIES["a known value"]
    writes = RestHost(azure_answers.OPEN)

    with known():
        AzureDevOpsForge(http=writes).post_comment(AZURE, 162, body=body)
        [write] = writes.writes()
        held = write.body["comments"][0]["content"]
        listing = RestHost(azure_answers.OPEN, threads={162: [top_level(901, held)]})
        found = AzureDevOpsForge(http=listing).comment_exists(AZURE, 162, COMMENT_MARKER, body)

    assert SECRET not in held
    assert found == "901.1"
