"""What git's output means, read in one adapter and pinned against recordings.

The fixtures under `tests/fixtures/external/git/` hold git's output with the
tool version in the header; a wording change in a later git fails here.
"""

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline import shell
from agent_build_kit.pipeline.git_output import git_push_outcome, replayed_files
from agent_build_kit.pipeline.restack import StaleRemote, push_with_lease
from tests.factories import git, init_repo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "external" / "git"


def recorded(name: str) -> subprocess.CompletedProcess[str]:
    """A fixture as the `CompletedProcess` git's caller received."""
    header, _, rest = (FIXTURES / f"{name}.txt").read_text().partition("--- stdout\n")
    stdout, _, stderr = rest.partition("--- stderr\n")
    returncode = next(
        int(line.split(":", 1)[1])
        for line in header.splitlines()
        if line.startswith("# returncode")
    )
    return subprocess.CompletedProcess(["git"], returncode, stdout, stderr)


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("push_stale_lease", "stale_lease"),
        ("push_hook_declined", "rejected_by_remote"),
        ("push_protected_branch", "rejected_by_remote"),
        ("push_non_fast_forward", "rejected_by_remote"),
        ("push_unrelated_failure", "other"),
    ],
)
def test_a_recorded_push_is_classified(name: str, kind: str) -> None:
    assert git_push_outcome(recorded(name)).kind == kind


def test_the_result_carries_what_the_remote_said() -> None:
    result = git_push_outcome(recorded("push_hook_declined"))

    assert "commit message must reference a ticket" in result.message


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "repo")
    (repo / "a.txt").write_text("a")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo


def push_answering(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make the push, and only the push, end as the recording says."""
    original = shell.git

    def answer(repo: Path, *args: str, **kwargs):
        if "push" in args:
            return recorded(name)
        return original(repo, *args, **kwargs)

    monkeypatch.setattr(shell, "git", answer)


def test_only_a_stale_lease_is_reported_as_someone_elses_push(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    push_answering(monkeypatch, "push_stale_lease")

    with pytest.raises(StaleRemote):
        push_with_lease(repo, "main", last_pushed="0" * 40)


@pytest.mark.parametrize(
    "name",
    [
        "push_hook_declined",
        "push_protected_branch",
        "push_non_fast_forward",
        "push_unrelated_failure",
    ],
)
def test_any_other_failure_is_not_reported_as_someone_elses_push(
    repo: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    push_answering(monkeypatch, name)

    with pytest.raises(RuntimeError) as raised:
        push_with_lease(repo, "main", last_pushed="0" * 40)

    assert not isinstance(raised.value, StaleRemote)
    assert recorded(name).stderr.splitlines()[0] in str(raised.value)


def test_a_hook_that_declines_a_real_push_is_not_a_stale_lease(repo: Path, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'not today' >&2\nexit 1\n")
    hook.chmod(0o755)

    with pytest.raises(RuntimeError) as raised:
        push_with_lease(repo, "main", last_pushed=None)

    assert not isinstance(raised.value, StaleRemote)
    assert "not today" in str(raised.value)


def test_the_push_runs_with_porcelain_and_a_fixed_locale(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    seen: list[tuple[tuple[str, ...], dict]] = []
    original = shell.git

    def spy(repo_arg: Path, *args: str, **kwargs):
        if "push" in args:
            seen.append((args, kwargs))
        return original(repo_arg, *args, **kwargs)

    monkeypatch.setattr(shell, "git", spy)
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    monkeypatch.setenv("LANGUAGE", "de")

    first = push_with_lease(repo, "main", last_pushed=None)
    push_with_lease(repo, "main", last_pushed=first)

    assert len(seen) == 2
    for args, kwargs in seen:
        assert "--porcelain" in args
        assert kwargs["env"]["LC_ALL"] == "C"
        assert kwargs["env"]["LANGUAGE"] == "C"


def test_a_recorded_replay_notice_yields_the_replayed_files() -> None:
    output = recorded("rebase_rerere_replay")

    assert replayed_files(output.stdout + output.stderr) == ["conflicted.py"]


def test_an_unrelated_line_is_not_a_replay() -> None:
    output = recorded("rebase_rerere_no_replay")

    assert replayed_files(output.stdout + output.stderr) == []


def test_a_line_that_only_quotes_the_notice_is_not_a_replay() -> None:
    assert replayed_files("hint: Resolved 'a.py' using previous resolution.\n") == []
