"""The GitHub forge: the identity half.

These are the cases `init.parse_slug` covered before the forges existed - the
same four URL forms, including the ssh host alias, which is why the GitHub
pattern has to stay permissive and be tried last.
"""

from __future__ import annotations

import pytest

from agent_build_kit import forges
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import FORGE


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:example/app.git",
        "https://github.com/example/app",
        "https://github.com/example/app.git",
        "ssh://git@github.com/example/app.git",
        "github-example:example/app.git",
    ],
)
def test_every_origin_form_yields_the_same_identity(url: str) -> None:
    repo = FORGE.parse_remote(url)

    assert repo is not None
    assert (repo.forge, repo.account, repo.name) == ("github", "example", "app")
    assert repo.project == "", "GitHub has no project segment"


def test_a_url_that_is_not_a_remote_is_refused() -> None:
    assert FORGE.parse_remote("/srv/git/app.git") is None
    assert FORGE.parse_remote("") is None


def test_the_identity_key_is_the_slug_the_rest_of_the_kit_uses() -> None:
    """`own-posts.json` and the poller's state are keyed on it, so it has to
    stay `owner/name` for GitHub or a running installation loses its history."""
    repo = FORGE.parse_remote("git@github.com:example/app.git")

    assert repo is not None
    assert forges.key(repo) == "example/app"


def test_the_web_url_points_at_the_pull_request() -> None:
    """`diagram.py` links every unit to its PR; it hardcoded github.com."""
    repo = FORGE.parse_remote("git@github.com:example/app.git")

    assert repo is not None
    assert forges.get("github").web_url(repo) == "https://github.com/example/app"
    assert forges.get("github").web_url(repo, pr=7) == "https://github.com/example/app/pull/7"


class FakeGh:
    """Records the argv of every gh call and answers with recorded output."""

    def __init__(self, stdout: str = "", json_out: object = None) -> None:
        self.commands: list[list[str]] = []
        self.stdout = stdout
        self.json_out = json_out

    def out(self, args: list[str], *, slug: str = "") -> str:
        self.commands.append(args)
        return self.stdout

    def json(self, args: list[str], *, slug: str = "", default: object = None) -> object:
        self.commands.append(args)
        return self.json_out if self.json_out is not None else default


def test_creating_a_pr_names_its_repo_and_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without `--repo`, gh infers it from the working directory's remote -
    right by luck, wrong the moment it is called from anywhere else."""
    fake = FakeGh(stdout="https://github.com/o/r/pull/7")
    monkeypatch.setattr("agent_build_kit.forges.github.gh_out", fake.out)
    repo = RepoId(forge="github", account="o", name="r")

    number = FORGE.create_pr(repo, head="spec/x/1", base="main", title="t", body="b")

    assert number == 7, "the PR number is the last segment of the URL gh prints"
    command = fake.commands[0]
    assert command[:3] == ["gh", "pr", "create"]
    assert "--repo" in command and "o/r" in command
    assert "--base" in command and "main" in command


def test_finding_a_pr_by_branch_names_its_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGh(json_out=[{"number": 11}])
    monkeypatch.setattr("agent_build_kit.forges.github.gh_json", fake.json)
    repo = RepoId(forge="github", account="o", name="r")

    assert FORGE.find_pr(repo, head="spec/x/1") == 11
    assert "--repo" in fake.commands[0]


def test_a_lookup_that_errors_reads_as_no_pr_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    """`gh_json` returns its default on failure, and a malformed answer must
    not read as a PR number - creating a second PR for the same branch is the
    failure this prevents."""
    fake = FakeGh(json_out=[{"unexpected": True}])
    monkeypatch.setattr("agent_build_kit.forges.github.gh_json", fake.json)

    assert FORGE.find_pr(RepoId(forge="github", account="o", name="r"), head="spec/x/1") is None


def test_a_reply_goes_to_the_comment_s_thread_and_reports_both_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reply creates a review of its own with an empty body — nothing to
    mark — so its id comes back too, for the poller to skip."""
    calls: list[list[str]] = []

    def fake_json(args: list[str], *, slug: str = "", default: object = None) -> object:
        calls.append(args)
        if "/replies" in args[4 if args[2:4] == ["-X", "POST"] else 2]:
            return {"node_id": "PRRC_11", "pull_request_review_id": 911}
        return {"node_id": "PRR_911"}

    monkeypatch.setattr("agent_build_kit.forges.github.gh_json", fake_json)
    repo = RepoId(forge="github", account="example", name="platform")

    ids = FORGE.post_reply(repo, 17, note_id="11", body="Now a frozen BaseModel.")

    assert ids == ["PRRC_11", "PRR_911"]
    assert calls[0][4] == "repos/example/platform/pulls/17/comments/11/replies"
    assert calls[1][2] == "repos/example/platform/pulls/17/reviews/911"


def test_a_summary_is_one_comment_on_the_pull_request(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGh(json_out={"node_id": "IC_summary"})
    monkeypatch.setattr("agent_build_kit.forges.github.gh_json", fake.json)
    repo = RepoId(forge="github", account="example", name="platform")

    assert FORGE.post_comment(repo, 17, body="Also dropped the /mcp key.") == ["IC_summary"]
    assert fake.commands[0][4] == "repos/example/platform/issues/17/comments"


def test_a_status_names_the_tested_commit_and_is_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHub rejects a description over 139 characters outright, which would
    lose the whole status rather than the tail of a sentence."""
    fake = FakeGh()
    monkeypatch.setattr("agent_build_kit.forges.github.gh", fake.out)
    repo = RepoId(forge="github", account="o", name="r")

    FORGE.post_status(repo, sha="abc1234def", ok=True, context="local/tier2", description="x" * 200)

    command = fake.commands[0]
    assert "repos/o/r/statuses/abc1234def" in command
    assert "state=success" in command
    assert f"description={'x' * 139}" in command
