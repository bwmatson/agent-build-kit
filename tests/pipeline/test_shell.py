"""The one place the pipeline shells out to git, and where a token is read from
the `gh` login.

A call against the other account's private repo reports it as nonexistent,
which reads exactly like a repo with no PRs, so the token follows the repo's
owner and is never whichever account is active.
"""

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline import shell


def test_git_out_strips_and_raises(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)

    assert shell.git_out(tmp_path, "symbolic-ref", "--short", "HEAD") == "main"
    with pytest.raises(subprocess.CalledProcessError):
        shell.git_out(tmp_path, "rev-parse", "no-such-ref")


def test_one_lookup_order_serves_every_caller(monkeypatch: pytest.MonkeyPatch) -> None:
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
