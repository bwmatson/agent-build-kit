"""A failed git push, fetch or ls-remote is read for what failed: the host refused, or the
host could not be reached. Either is an outage, never a verdict on the branch.

The outputs are git's, in its fixed locale (`LC_ALL=C`), as the push and the fetch run it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.pipeline import restack
from agent_build_kit.pipeline.git_output import git_push_outcome, transport_failure
from agent_build_kit.pipeline.restack import StaleRemote, push_with_lease
from agent_build_kit.runtimes import NetworkUnavailable
from tests.pipeline.test_git_output import recorded

COULD_NOT_READ = """fatal: Could not read from remote repository.

Please make sure you have the correct access rights
and the repository exists.
"""

# What the unit's push printed on 2026-11-04, and the same refusal as a fetch prints it.
PERMISSION_DENIED = "git@github.com: Permission denied (publickey).\n" + COULD_NOT_READ

REFUSED = {
    "the real refusal": PERMISSION_DENIED,
    "the bare line": "git@github.com: Permission denied (publickey).",
    "an https login refused": "remote: Invalid username or password.\n"
    "fatal: Authentication failed for 'https://github.com/example/app.git/'",
    "a 401": "fatal: unable to access 'https://github.com/example/app.git/': "
    "The requested URL returned error: 401",
    "a 403": "error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403",
    "a 500": "fatal: unable to access 'https://github.com/example/app.git/': "
    "The requested URL returned error: 500",
    "a 503": "error: The requested URL returned error: 503\nfatal: the remote end hung up",
    "closed by the host": "Connection closed by remote host\n" + COULD_NOT_READ,
    "closed by an address": "Connection closed by 140.82.112.4 port 22\n" + COULD_NOT_READ,
    "an exchange that failed": "ssh_exchange_identification: Connection closed by remote host\n"
    + COULD_NOT_READ,
}

UNREACHABLE = {
    "a name that does not resolve": "fatal: unable to access "
    "'https://github.com/example/app.git/': Could not resolve host: github.com",
    "a name ssh cannot resolve": "ssh: Could not resolve hostname github.com: "
    "Temporary failure in name resolution\n" + COULD_NOT_READ,
    "a timed-out connect": "ssh: connect to host github.com port 22: Connection timed out\n"
    + COULD_NOT_READ,
    "a refused connect": "ssh: connect to host github.com port 22: Connection refused\n"
    + COULD_NOT_READ,
    "a reset": "Connection reset by 140.82.112.4 port 22\n" + COULD_NOT_READ,
    "a reset by the peer": "fatal: unable to access 'https://github.com/example/app.git/': "
    "OpenSSL SSL_read: Connection reset by peer, errno 104",
    "an unreachable network": "ssh: connect to host github.com port 22: Network is unreachable\n"
    + COULD_NOT_READ,
}

OTHER = {
    "a repository that is not there": "fatal: '/srv/git/nowhere.git' does not appear to be a "
    "git repository\n" + COULD_NOT_READ,
    "nothing at all": "",
    "an unrelated error": "error: failed to push some refs to 'origin'",
}


@pytest.mark.parametrize("output", REFUSED.values(), ids=REFUSED)
def test_a_refusal_by_the_host_is_told_from_the_output(output: str) -> None:
    failure = transport_failure(output)

    assert failure is not None
    assert failure.kind == "refused"
    assert failure.message == output.strip()


@pytest.mark.parametrize("output", UNREACHABLE.values(), ids=UNREACHABLE)
def test_a_failure_to_reach_the_host_is_told_from_the_output(output: str) -> None:
    failure = transport_failure(output)

    assert failure is not None
    assert failure.kind == "unreachable"


@pytest.mark.parametrize("output", OTHER.values(), ids=OTHER)
def test_any_other_failure_is_no_outage(output: str) -> None:
    assert transport_failure(output) is None


def failed_push(stderr: str, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", "push"], 128, stdout, stderr)


@pytest.mark.parametrize("output", REFUSED.values(), ids=REFUSED)
def test_a_push_the_host_refused_is_told_apart_from_the_rest(output: str) -> None:
    assert git_push_outcome(failed_push(output)).kind == "host_refused"


@pytest.mark.parametrize("output", UNREACHABLE.values(), ids=UNREACHABLE)
def test_a_push_that_could_not_reach_the_host_is_told_apart_from_the_rest(output: str) -> None:
    assert git_push_outcome(failed_push(output)).kind == "host_unreachable"


def test_a_rejected_ref_is_never_an_outage_whatever_else_the_remote_said() -> None:
    result = failed_push(
        "remote: error: GH006: Protected branch update failed; returned error: 403\n"
        "error: failed to push some refs to 'origin'",
        "!\trefs/heads/b:refs/heads/b\t[remote rejected] (protected branch hook declined)\n",
    )

    assert git_push_outcome(result).kind == "rejected_by_remote"


def test_a_stale_lease_is_never_an_outage() -> None:
    result = failed_push(
        "Connection reset by peer", "!\trefs/heads/b:refs/heads/b\t[rejected] (stale info)\n"
    )

    assert git_push_outcome(result).kind == "stale_lease"


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
def test_the_recorded_outputs_keep_their_kind(name: str, kind: str) -> None:
    assert git_push_outcome(recorded(name)).kind == kind


# --- the push --------------------------------------------------------------------------


class FailingGit:
    """`git` as `push_with_lease` calls it: the push fails with `stderr`, the remote has `url`."""

    def __init__(
        self, stderr: str, *, stdout: str = "", url: str = "git@github.com:example/app.git"
    ):
        self.stderr, self.stdout, self.url = stderr, stdout, url

    def __call__(
        self, repo: Path, *args: str, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if args[0] == "push":
            return subprocess.CompletedProcess(args, 128, self.stdout, self.stderr)
        if args[:2] == ("remote", "get-url"):
            return subprocess.CompletedProcess(args, 0, self.url + "\n", "")
        raise AssertionError(f"git {args} is not what a failed push does")


@pytest.fixture
def pushing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Pushes `b` through `push_with_lease` when the push ends as given."""
    monkeypatch.setattr(restack.shell, "has_origin", lambda repo: True)

    def push(failing: FailingGit, last_pushed: str | None = None) -> str:
        monkeypatch.setattr(restack, "git", failing)
        return push_with_lease(tmp_path, "b", last_pushed=last_pushed)

    return push


@pytest.mark.parametrize("last_pushed", [None, "a" * 40], ids=["first push", "a lease"])
def test_a_push_the_host_refuses_raises_the_code_host_outage(pushing, last_pushed) -> None:
    with pytest.raises(HostUnavailable) as raised:
        pushing(FailingGit(PERMISSION_DENIED), last_pushed)

    assert "Permission denied (publickey)" in str(raised.value)


@pytest.mark.parametrize(
    ("url", "port"),
    [
        ("git@github.com:example/app.git", 22),
        ("ssh://git@github.com/example/app.git", 22),
        ("ssh://git@github.com:2222/example/app.git", 2222),
        ("https://github.com/example/app.git", 443),
        ("https://github.com:8443/example/app.git", 8443),
    ],
)
def test_a_push_that_cannot_reach_the_host_raises_a_weak_network_outage_for_the_remote(
    pushing, url: str, port: int
) -> None:
    with pytest.raises(NetworkUnavailable) as raised:
        pushing(FailingGit(UNREACHABLE["a timed-out connect"], url=url))

    assert (raised.value.strength, raised.value.host, raised.value.port) == (
        "weak",
        "github.com",
        port,
    )
    assert raised.value.service == "code_host"


def test_a_stale_lease_still_raises_the_stale_remote(pushing) -> None:
    failing = FailingGit("", stdout="!\trefs/heads/b:refs/heads/b\t[rejected] (stale info)\n")

    with pytest.raises(StaleRemote):
        pushing(failing, "a" * 40)


@pytest.mark.parametrize(
    "output", [recorded("push_hook_declined"), recorded("push_unrelated_failure")]
)
def test_a_rejected_ref_and_an_unclassified_failure_are_plain_errors(
    pushing, output: subprocess.CompletedProcess[str]
) -> None:
    with pytest.raises(RuntimeError) as raised:
        pushing(FailingGit(output.stderr, stdout=output.stdout))

    assert type(raised.value) is RuntimeError
