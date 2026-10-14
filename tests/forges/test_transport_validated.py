"""The step that validates a body and names the endpoint is shared by both hosts."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_build_kit.forges import azure_devops, github
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.transport import PAGE_EXCERPT, TransportError, validated
from tests.forges.azure_rest_host import RestHost, answer
from tests.forges.github_host import GitHubHost

BASE = "/repos/example/app"


pytestmark = pytest.mark.usefixtures("github_env", "rest_env")


class Doc(BaseModel):
    name: str


def test_a_body_that_validates_comes_back_as_the_model() -> None:
    assert validated(Doc, {"name": "x"}, "GET things", '{"name": "x"}') == Doc(name="x")


def test_a_body_that_does_not_validate_names_the_endpoint_and_quotes_the_start_of_it() -> None:
    text = '{"name": 5}' + " " * PAGE_EXCERPT + "tail"

    with pytest.raises(TransportError) as raised:
        validated(Doc, {"name": 5}, "GET things", text)

    assert str(raised.value) == f"GET things: not the document expected: {text[:PAGE_EXCERPT]}"


def test_a_quoted_page_that_the_cut_leaves_in_a_code_fence_closes_it() -> None:
    text = "```\n" + "a line of the page\n" * 40

    with pytest.raises(TransportError) as raised:
        validated(Doc, {"name": 5}, "GET things", text)

    quoted = str(raised.value).removeprefix("GET things: not the document expected: ")
    assert len(quoted) <= PAGE_EXCERPT
    assert quoted.startswith("```\na line of the page")
    assert quoted.endswith("```")


class Seen:
    def __init__(self) -> None:
        self.endpoints: list[str] = []

    def __call__(self, model, data, endpoint, text):
        self.endpoints.append(endpoint)
        raise TransportError(f"{endpoint}: seen")


def test_github_lists_through_the_shared_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = Seen()
    monkeypatch.setattr(github, "validated", seen)
    host = GitHubHost(paged={f"{BASE}/pulls/7/files": [{"filename": 5}]})

    with pytest.raises(TransportError, match="seen"):
        github.GitHubForge(http=host).pr_files(
            RepoId(forge="github", account="example", name="app"), 7
        )

    assert seen.endpoints == ["list_files"]


def test_azure_devops_lists_through_the_shared_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = Seen()
    monkeypatch.setattr(azure_devops, "validated", seen)
    host = RestHost(refuse={("GET", "pullrequests"): answer({"value": [{"pullRequestId": "x"}]})})
    repo = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")

    with pytest.raises(TransportError, match="seen"):
        azure_devops.AzureDevOpsForge(http=host).list_prs(repo)

    assert len(seen.endpoints) == 1
