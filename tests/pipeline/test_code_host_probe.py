"""The authenticated probe of a code host (spec: git-host-outage, each code host has one marker and
one authenticated check): `git ls-remote <remote> HEAD` over the transport a push uses, so a refused
key fails it where a bare connect passes, and a probe that cannot run counts the host healthy.

`git` is a stand-in: no test here touches a network."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline import network_probe
from tests.code_host_fixtures import GITHUB_URL, REFUSED
from tests.factories import git, init_repo

TIMEOUT = 5


class FakeGit:
    """The `run` seam of the probe: records each call and ends as told."""

    def __init__(
        self, *, returncode: int = 0, stderr: str = "", raises: BaseException | None = None
    ) -> None:
        self.returncode, self.stderr, self.raises = returncode, stderr, raises
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, stdout="", stderr=self.stderr)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "app")
    git(repo, "remote", "add", "origin", GITHUB_URL)
    return repo


def probe(checkout: Path, run: FakeGit) -> network_probe.HostProbe:
    return network_probe.code_host_healthy(checkout, timeout=TIMEOUT, run=run)


def test_a_read_of_head_that_succeeds_is_healthy(checkout: Path) -> None:
    run = FakeGit()

    assert probe(checkout, run) == network_probe.HostProbe(healthy=True)

    [(argv, kwargs)] = run.calls
    assert argv[:2] == ["git", "ls-remote"] and argv[-1] == "HEAD"
    assert kwargs["cwd"] == checkout
    assert kwargs["timeout"] >= TIMEOUT


def test_the_probe_never_prompts_and_reads_git_in_its_fixed_locale(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    run = FakeGit()

    probe(checkout, run)

    env = run.calls[0][1]["env"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["LC_ALL"] == "C"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]


def test_the_ssh_command_a_push_uses_is_kept_and_made_batch(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /keys/pipeline")
    run = FakeGit()

    probe(checkout, run)

    command = run.calls[0][1]["env"]["GIT_SSH_COMMAND"]
    assert command.startswith("ssh -i /keys/pipeline") and "BatchMode=yes" in command


def test_a_refused_key_is_unhealthy_where_a_bare_connect_passes(checkout: Path) -> None:
    run = FakeGit(
        returncode=128,
        stderr=f"{REFUSED}\nfatal: Could not read from remote repository.\n",
    )

    reached = network_probe.host_connects(
        "github.com",
        22,
        timeout=TIMEOUT,
        resolve=lambda host: None,
        connect=lambda host, port, timeout: None,
    )
    result = probe(checkout, run)

    assert reached, "the host accepts a connection"
    assert not result.healthy
    assert "Permission denied (publickey)" in result.error


@pytest.mark.parametrize(
    "said",
    [
        "fatal: unable to access 'https://x/': The requested URL returned error: 503",
        "fatal: unable to access 'https://x/': Could not resolve host: github.com",
        "ssh: connect to host github.com port 22: Connection timed out",
    ],
)
def test_an_outage_by_the_hosts_own_words_is_unhealthy(checkout: Path, said: str) -> None:
    result = probe(checkout, FakeGit(returncode=128, stderr=said))

    assert not result.healthy and said in result.error


def test_a_run_that_times_out_is_unhealthy_and_says_so(checkout: Path) -> None:
    result = probe(checkout, FakeGit(raises=subprocess.TimeoutExpired("git", TIMEOUT)))

    assert not result.healthy
    assert "timed out" in result.error


@pytest.mark.parametrize(
    "said",
    [
        "ERROR: Repository not found.\nfatal: Could not read from remote repository.",
        "remote: Permission to example/app.git denied to someone.\nfatal: unable to access",
    ],
)
def test_a_refusal_a_person_has_to_fix_is_no_outage(checkout: Path, said: str) -> None:
    assert probe(checkout, FakeGit(returncode=128, stderr=said)).healthy


@pytest.mark.parametrize(
    "raises", [FileNotFoundError("git"), RuntimeError("a bug"), OSError("no fork")]
)
def test_a_probe_that_cannot_run_counts_the_host_healthy(
    checkout: Path, raises: BaseException
) -> None:
    assert probe(checkout, FakeGit(raises=raises)).healthy


def test_a_repo_with_no_remote_is_healthy_and_asks_nothing(tmp_path: Path) -> None:
    run = FakeGit(returncode=128, stderr=REFUSED)

    assert probe(init_repo(tmp_path / "bare"), run).healthy
    assert run.calls == []


def test_a_checkout_that_is_not_there_is_healthy_and_asks_nothing(tmp_path: Path) -> None:
    run = FakeGit(returncode=128, stderr=REFUSED)

    assert probe(tmp_path / "gone", run).healthy
    assert run.calls == []


def test_a_custom_ssh_program_is_left_alone(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GIT_SSH` names the program a push runs; a `GIT_SSH_COMMAND` from the probe would replace
    it."""
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.setenv("GIT_SSH", "/opt/wrapper/ssh")
    run = FakeGit()

    probe(checkout, run)

    assert "GIT_SSH_COMMAND" not in run.calls[0][1]["env"]
    assert run.calls[0][1]["env"]["GIT_SSH"] == "/opt/wrapper/ssh"


def test_a_configured_ssh_command_is_kept_and_made_batch(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.setenv("GIT_SSH", "/opt/wrapper/ssh")
    git(checkout, "config", "core.sshCommand", "ssh -i /keys/configured")
    run = FakeGit()

    probe(checkout, run)

    command = run.calls[0][1]["env"]["GIT_SSH_COMMAND"]
    assert command == "ssh -i /keys/configured -o BatchMode=yes"


def test_plain_ssh_is_made_batch_when_nothing_else_is_set(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.delenv("GIT_SSH", raising=False)
    run = FakeGit()

    probe(checkout, run)

    assert run.calls[0][1]["env"]["GIT_SSH_COMMAND"] == "ssh -o BatchMode=yes"
