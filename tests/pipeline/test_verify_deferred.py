"""A failed verification names the units of the change that deferred their e2e-test run.

`verify` selects and runs what it always has; only the failure's detail gains the note.
"""

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import E2eState, StoredUnit
from agent_build_kit.pipeline.verify import Verification, verify_change
from tests.conftest import make_installation
from tests.factories import stored_unit

FILES = {
    ("platform", 30): ["svc-a/src/mcp.py"],
    ("platform", 31): ["svc-a/tests/integration/test_drive_live_stack.py"],
}
DEPLOY = {"rules": [{"prefix": "svc-a/", "run": [["scripts/deploy.sh", "svc-a"]]}]}


class Host:
    """Records every command; the checkouts are clean and on main, and a command
    containing `failing` fails with a short output."""

    def __init__(self, *, failing: str = "") -> None:
        self.calls: list[tuple[str, ...]] = []
        self.failing = failing

    def __call__(self, command, *, cwd, env=None, **kwargs):
        self.calls.append(tuple(command))
        out, code = "", 0
        if command[:2] == ["git", "rev-parse"]:
            out = "main"
        elif self.failing and self.failing in " ".join(command):
            out, code = "1 failed in 2.00s\nAssertionError: no tools", 1
        return subprocess.CompletedProcess(command, code, out, "")


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    path = tmp_path / "checkouts" / "platform"
    installation = make_installation(
        tmp_path,
        repos={"platform": {"path": str(path), "slug": "example/platform", "deploy": DEPLOY}},
    )
    (path / "svc-a" / "tests" / "integration").mkdir(parents=True)
    (path / "svc-a" / "pyproject.toml").write_text('[project]\nname = "svc-a"\n')
    (path / "svc-a" / "tests" / "integration" / "test_drive_live_stack.py").touch()
    return installation


def merged(uid: str, pr: int, e2e_state: E2eState | None) -> StoredUnit:
    return stored_unit(uid, change="c", repo="platform", state="merged", pr=pr, e2e_state=e2e_state)


def verify(host: Host, inst: Installation, *states: E2eState | None) -> Verification:
    units = [merged(f"c/{n}", 29 + n, state) for n, state in enumerate(states, start=1)]
    return verify_change(
        "c",
        units,
        installation=inst,
        pr_files=lambda repo, pr: FILES[(repo, pr)],
        run=host,
        env={},
    )


def test_a_deferral_changes_neither_the_deploy_nor_the_live_tests(inst) -> None:
    plain, deferring = Host(), Host()

    verify(plain, inst, E2eState.PASSED, E2eState.NOT_REQUIRED)
    verify(deferring, inst, E2eState.DEFERRED, E2eState.PASSED)

    assert deferring.calls == plain.calls
    assert any("pytest" in command for command in plain.calls)
    assert ("scripts/deploy.sh", "svc-a") in plain.calls
    # the same commands run when it fails, and then the detail says what was deferred
    failing = Host(failing="pytest")
    assert "c/1" in verify(failing, inst, E2eState.DEFERRED, E2eState.PASSED).detail
    assert failing.calls == plain.calls


def test_a_failure_names_the_unit_that_deferred_its_e2e(inst) -> None:
    result = verify(Host(failing="pytest"), inst, E2eState.DEFERRED, E2eState.PASSED)

    assert not result.passed
    assert "no tools" in result.detail, "the failure itself stays in the detail"
    assert "c/1" in result.detail
    assert "c/2" not in result.detail
    assert "deferred" in result.detail


def test_a_failure_names_every_deferred_unit(inst) -> None:
    result = verify(Host(failing="pytest"), inst, E2eState.DEFERRED, E2eState.DEFERRED)

    assert "c/1" in result.detail
    assert "c/2" in result.detail


def test_a_failure_with_no_deferred_unit_has_the_detail_it_has_today(inst) -> None:
    result = verify(Host(failing="pytest"), inst, E2eState.PASSED, None)

    assert not result.passed
    assert "deferred" not in result.detail
    assert result.detail.startswith("live tests failed — platform:")
    deferred = verify(Host(failing="pytest"), inst, E2eState.DEFERRED, None)
    assert deferred.detail.endswith(result.detail) and deferred.detail != result.detail


def test_a_passing_verification_is_unchanged_by_a_deferral(inst) -> None:
    result = verify(Host(), inst, E2eState.DEFERRED, E2eState.PASSED)

    assert result.passed
    assert result.detail == ""
    assert result.deployed == ["platform: scripts/deploy.sh svc-a"]
    failed = verify(Host(failing="pytest"), inst, E2eState.DEFERRED, E2eState.PASSED)
    assert "c/1" in failed.detail, "the note belongs to a failure alone"
