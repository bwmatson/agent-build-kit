"""The one place the pipeline shells out to git and gh.

What matters most here is that a `gh` call cannot run as the wrong account.
The two code repos are on two GitHub accounts and `gh` has one active at a
time; a call against the other account's private repo reports it as
nonexistent, which reads exactly like a repo with no PRs. The poller once ran
clean for exactly that reason while seeing nothing of app.
"""

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline import shell


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_run(args, **kwargs):
        calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(args, 0, "[]", "")

    monkeypatch.setattr(shell.subprocess, "run", fake_run)
    monkeypatch.setattr(shell, "token_for", lambda owner: f"token-for-{owner}")
    monkeypatch.setattr(shell.settings, "gh_token", "")
    return calls


def test_a_configured_token_is_used_for_every_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """One account can hold access to both repos, and saying so in settings is
    simpler than inferring it from who owns what."""
    monkeypatch.setattr(shell.settings, "gh_token", "configured")

    assert shell.gh_env("example/platform")["GH_TOKEN"] == "configured"
    assert shell.gh_env("example/app")["GH_TOKEN"] == "configured"


def test_without_one_the_token_follows_the_repo_s_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell.settings, "gh_token", "")
    monkeypatch.setattr(shell, "token_for", lambda owner: f"token-for-{owner}")

    assert shell.gh_env("example/platform")["GH_TOKEN"] == "token-for-example"
    assert shell.gh_env("example/app")["GH_TOKEN"] == "token-for-example"


def test_the_repo_a_gh_command_names_is_what_picks_the_token() -> None:
    assert shell.slug_in(["gh", "pr", "list", "--repo", "a/b"]) == "a/b"
    assert shell.slug_in(["gh", "pr", "list"]) == ""


def test_every_gh_call_runs_as_the_repo_s_owner(captured: list[dict]) -> None:
    """The reason this module exists: there is no way to call gh here without
    the token being chosen, so a new call site cannot forget it."""
    shell.gh(["gh", "pr", "list", "--repo", "example/platform"])

    assert captured[0]["env"]["GH_TOKEN"] == "token-for-example"


def test_a_repo_named_in_a_path_is_passed_explicitly(captured: list[dict]) -> None:
    """`gh api repos/<owner>/<name>/...` has no --repo flag to read the owner
    from; without `slug` it would run as whichever account is active."""
    shell.gh(["gh", "api", "repos/example/platform/pulls/16/comments"], slug="example/platform")

    assert captured[0]["env"]["GH_TOKEN"] == "token-for-example"


def test_gh_json_falls_back_rather_than_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """For reads where "could not tell" and "nothing there" lead to the same
    action — neither a failed call nor unparseable output may escape."""
    for rc, out in ((1, "[]"), (0, "not json"), (0, "")):
        monkeypatch.setattr(
            shell.subprocess,
            "run",
            lambda args, _rc=rc, _out=out, **k: subprocess.CompletedProcess(args, _rc, _out, ""),
        )
        monkeypatch.setattr(shell, "token_for", lambda owner: None)
        assert shell.gh_json(["gh", "api", "x"]) == []


def test_gh_out_names_the_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Callers that must tell failure from emptiness get the reason, not an
    empty string that reads as "nothing found"."""
    monkeypatch.setattr(
        shell.subprocess,
        "run",
        lambda args, **k: subprocess.CompletedProcess(args, 1, "", "HTTP 404"),
    )
    monkeypatch.setattr(shell, "token_for", lambda owner: None)

    with pytest.raises(RuntimeError, match="HTTP 404"):
        shell.gh_out(["gh", "pr", "list", "--repo", "a/b"])


def test_git_out_strips_and_raises(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)

    assert shell.git_out(tmp_path, "symbolic-ref", "--short", "HEAD") == "main"
    with pytest.raises(subprocess.CalledProcessError):
        shell.git_out(tmp_path, "rev-parse", "no-such-ref")


def test_one_lookup_order_serves_gh_and_http_callers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The setting, then the owner's `gh` login; the source names which."""
    monkeypatch.setattr(shell.settings, "gh_token", "configured")
    assert shell.credential_source("example") == ("configured", "GH_TOKEN")

    monkeypatch.setattr(shell.settings, "gh_token", "")
    monkeypatch.setattr(shell, "token_for", lambda owner: f"token-for-{owner}")
    assert shell.credential_source("example") == (
        "token-for-example",
        "gh auth token --user example",
    )

    monkeypatch.setattr(shell, "token_for", lambda owner: None)
    assert shell.credential_source("example") is None


def test_an_injected_run_reads_the_login_afresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell.settings, "gh_token", "")
    seen: list[list[str]] = []

    def run(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "tok\n", "")

    assert shell.credential_source("example", run=run) == (
        "tok",
        "gh auth token --user example",
    )
    assert seen == [["gh", "auth", "token", "--user", "example"]]
