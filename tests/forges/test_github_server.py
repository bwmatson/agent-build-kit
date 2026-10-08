"""The fake GitHub host a process test points `ABK_GITHUB_API_URL` at: the routes
a unit's life uses, answered over real HTTP from the recorded shapes, with state
the test drives; the credential it requires; the routes it refuses.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator

import httpx
import pytest

from agent_build_kit.forges.base import Label, RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.settings import settings
from tests.forges.github_server import FakeGitHub

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"
HEAD = "spec/add-marker/1"
OPEN = {"head": HEAD, "base": "main", "title": "add-marker/1: Register the marker", "body": "b"}


@pytest.fixture
def client(github_server: FakeGitHub) -> Iterator[httpx.Client]:
    headers = {"authorization": f"Bearer {github_server.token}"}
    with httpx.Client(base_url=github_server.url, headers=headers) as http:
        yield http


@pytest.fixture
def forge(github_server: FakeGitHub, monkeypatch: pytest.MonkeyPatch) -> GitHubForge:
    monkeypatch.setattr(settings, "github_api_url", github_server.url)
    monkeypatch.setattr(settings, "gh_token", github_server.token)
    clear_credentials()
    return GitHubForge()


# --- the routes a unit's life uses ----------------------------------------------------


def test_a_create_then_a_lookup_by_head_finds_the_pull_request(client: httpx.Client) -> None:
    made = client.post(f"{BASE}/pulls", json=OPEN)
    found = client.get(f"{BASE}/pulls", params={"head": f"example:{HEAD}", "state": "all"})

    assert made.status_code == 201
    assert made.json()["number"] == 1
    assert made.json()["head"]["ref"] == HEAD
    assert made.json()["base"]["ref"] == "main"
    assert [p["number"] for p in found.json()] == [1]
    assert client.get(f"{BASE}/pulls", params={"head": "example:other"}).json() == []


def test_numbers_start_where_the_test_says() -> None:
    with FakeGitHub(first_number=7) as server:
        headers = {"authorization": f"Bearer {server.token}"}
        made = httpx.post(f"{server.url}{BASE}/pulls", json=OPEN, headers=headers)

    assert made.json()["number"] == 7


def test_a_duplicate_create_is_refused_as_github_refuses_it(client: httpx.Client) -> None:
    client.post(f"{BASE}/pulls", json=OPEN)

    again = client.post(f"{BASE}/pulls", json=OPEN)

    assert again.status_code == 422
    body = again.json()
    assert body["message"] == "Validation Failed"
    assert f"A pull request already exists for example:{HEAD}" in str(body["errors"])


def test_a_pull_request_reads_back_by_number(client: httpx.Client) -> None:
    client.post(f"{BASE}/pulls", json=OPEN)

    one = client.get(f"{BASE}/pulls/1")

    assert one.status_code == 200
    assert one.json()["number"] == 1
    assert one.json()["node_id"]
    assert client.get(f"{BASE}/pulls/9").status_code == 404


def test_the_listing_the_poller_reads_shows_the_pull_request_open(forge: GitHubForge) -> None:
    forge.create_pr(REPO, head=HEAD, base="main", title="t", body="b")

    [pull] = forge.list_prs(REPO)

    assert (pull.number, pull.head, pull.base, pull.state) == (1, HEAD, "main", "open")
    assert pull.conversation == ()
    assert pull.review_decision == ""
    assert pull.mergeable is True


def test_a_comment_the_test_writes_shows_in_the_next_read(
    github_server: FakeGitHub, forge: GitHubForge
) -> None:
    forge.create_pr(REPO, head=HEAD, base="main", title="t", body="b")
    before = forge.list_prs(REPO)[0]

    github_server.add_comment(1, "please rename the marker")

    after = forge.list_prs(REPO)[0]
    assert len(after.conversation) == len(before.conversation) + 1
    assert after.comment_bodies == ("please rename the marker",)


def test_a_review_the_test_writes_shows_in_the_next_read_and_in_its_notes(
    github_server: FakeGitHub, forge: GitHubForge
) -> None:
    forge.create_pr(REPO, head=HEAD, base="main", title="t", body="b")

    github_server.add_review(1, "CHANGES_REQUESTED", "the marker needs a test")

    [pull] = forge.list_prs(REPO)
    assert pull.review_decision == "changes_requested"
    assert len(pull.conversation) == 1
    assert [note.body for note in forge.review_notes(REPO, 1)] == ["the marker needs a test"]


def test_a_merge_the_test_makes_shows_in_the_next_read(
    github_server: FakeGitHub, forge: GitHubForge
) -> None:
    forge.create_pr(REPO, head=HEAD, base="main", title="t", body="b")

    github_server.merge(1)

    [pull] = forge.list_prs(REPO)
    assert pull.state == "merged"
    assert forge.find_pr(REPO, head=HEAD) == 1


def test_labels_attached_through_the_forge_show_in_the_next_read(forge: GitHubForge) -> None:
    forge.create_pr(REPO, head=HEAD, base="main", title="t", body="b")
    label = Label(name="running", color="d97706", description="Building")

    forge.add_label(REPO, 1, label)

    assert forge.list_prs(REPO)[0].labels == ("running",)
    forge.remove_label(REPO, 1, "running")
    assert forge.list_prs(REPO)[0].labels == ()


def test_a_draft_change_shows_in_the_next_read(forge: GitHubForge) -> None:
    forge.create_pr(REPO, head=HEAD, base="main", title="t", body="b")

    forge.set_draft(REPO, 1, True)

    assert forge.list_prs(REPO)[0].draft is True


# --- the credential and the routes it does not serve -----------------------------------


def test_a_request_without_the_token_gets_401(github_server: FakeGitHub) -> None:
    bare = httpx.get(f"{github_server.url}{BASE}/pulls")
    wrong = httpx.get(f"{github_server.url}{BASE}/pulls", headers={"authorization": "Bearer nope"})

    assert bare.status_code == 401
    assert wrong.status_code == 401
    assert bare.json()["message"] == "Bad credentials"
    assert github_server.requests() == []


def test_a_route_not_served_gets_a_404_naming_the_method_and_path(
    github_server: FakeGitHub, client: httpx.Client
) -> None:
    refused = client.post(f"{BASE}/forks", json={})

    assert refused.status_code == 404
    assert "POST" in refused.text
    assert f"{BASE}/forks" in refused.text
    assert github_server.unrouted() == [("POST", f"{BASE}/forks")]


def test_a_served_route_is_not_recorded_as_unrouted(
    github_server: FakeGitHub, client: httpx.Client
) -> None:
    client.post(f"{BASE}/pulls", json=OPEN)

    assert github_server.unrouted() == []
    assert github_server.requests("POST", f"{BASE}/pulls") == [("POST", f"{BASE}/pulls")]


# --- the forge reaches it through the setting -------------------------------------------


def test_the_forge_creates_and_finds_a_pull_request_with_the_credential_the_stand_in_prints(
    github_server: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No token setting: the credential is what `gh auth token` prints."""

    def gh(argv, **kwargs):
        assert list(argv[:3]) == ["gh", "auth", "token"]
        return subprocess.CompletedProcess(argv, 0, f"{github_server.token}\n", "")

    monkeypatch.setattr(settings, "gh_token", "")
    monkeypatch.setattr(settings, "github_api_url", github_server.url)
    monkeypatch.setattr(subprocess, "run", gh)
    clear_credentials()
    forge = GitHubForge()

    number = forge.create_pr(REPO, head=HEAD, base="main", title="t", body="b")

    assert number == 1
    assert forge.find_pr(REPO, head=HEAD) == 1
    assert github_server.unrouted() == []
    assert ("POST", f"{BASE}/pulls") in github_server.requests()


def test_a_wrong_credential_fails_the_forge_the_way_the_host_does(
    github_server: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "gh_token", "not-the-token")
    monkeypatch.setattr(settings, "github_api_url", github_server.url)
    monkeypatch.setattr(settings, "forge_retries", 0)
    clear_credentials()

    with pytest.raises(Exception, match="401|Bad credentials"):
        GitHubForge().create_pr(REPO, head=HEAD, base="main", title="t", body="b")
