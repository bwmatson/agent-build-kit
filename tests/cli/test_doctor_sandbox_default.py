"""With the sandbox on by default, `abk doctor` names the outcome for each repo, `abk status`
shows coverage `none` where no backend exists, and `abk init` writes no `sandbox:` block (spec:
sandbox-default)."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import yaml

from agent_build_kit import sandboxes
from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import load
from agent_build_kit.sandboxes import Coverage
from agent_build_kit.settings import reload
from tests.cli.guard_listing_support import ACTIVE, state_of
from tests.cli.test_doctor import Answers
from tests.cli.test_doctor import workspace as off_workspace  # noqa: F401 — fixture
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures
from tests.conftest import make_installation
from tests.factories import recognised_planning, which_all
from tests.runtimes.selectable import SelectableRuntime, select
from tests.sandboxes.stand_in import StandInBackend

pytestmark = pytest.mark.sandbox_probe

ELSEWHERE = "no-such-platform"
REPOS = ("app", "platform")


@pytest.fixture
def workspace(off_workspace: Path) -> Path:  # noqa: F811 — fixture
    """The shared doctor workspace with the `sandbox` block it writes taken out, so the sandbox
    is left at its default."""
    config = off_workspace / "abk.yaml"
    document = yaml.safe_load(config.read_text())
    document.pop("sandbox", None)
    config.write_text(yaml.safe_dump(document))
    return off_workspace


@pytest.fixture
def working_backend() -> Iterator[None]:
    with sandboxes.isolated():
        sandboxes.register(StandInBackend("landlock", "", runs_as_given=True))
        yield


@pytest.fixture
def no_backend() -> Iterator[None]:
    with sandboxes.isolated():
        sandboxes.register(StandInBackend("landlock", ELSEWHERE))
        sandboxes.register(StandInBackend("seatbelt", ELSEWHERE))
        yield


@pytest.fixture
def failing_backend() -> Iterator[None]:
    with sandboxes.isolated():
        sandboxes.register(StandInBackend("landlock", "", ok=False))
        yield


def sandbox_check(config: Path) -> Check:
    """The one sandbox check of a workspace that writes no `sandbox` block."""
    checks = run_doctor(config, run=Answers(), which=which_all)
    (found,) = [c for c in checks if "sandbox" in c.name]
    return found


def test_doctor_names_a_working_backend_and_every_repo_it_confines(
    workspace: Path,  # noqa: F811 — fixture
    working_backend: None,
) -> None:
    found = sandbox_check(workspace / "abk.yaml")

    assert found.status == "ok"
    assert "landlock" in found.detail
    assert all(repo in found.detail for repo in REPOS)


def test_doctor_says_a_machine_with_no_backend_runs_every_repo_unconfined(
    workspace: Path,  # noqa: F811 — fixture
    no_backend: None,
) -> None:
    found = sandbox_check(workspace / "abk.yaml")

    assert found.status == "info"
    assert "unconfined" in found.detail
    assert all(repo in found.detail for repo in REPOS)


def test_doctor_fails_a_backend_that_does_not_work_with_the_cause_and_the_fix(
    workspace: Path,  # noqa: F811 — fixture
    failing_backend: None,
) -> None:
    found = sandbox_check(workspace / "abk.yaml")

    assert found.status == "FAIL"
    assert "stand-in off" in found.detail
    assert "turn on" in found.fix


@pytest.fixture
def runtime_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    """Selects a runtime by name; the cached settings are reloaded again at teardown."""

    def use(name: str) -> None:
        monkeypatch.setenv("ABK_RUNTIME", name)
        reload(None)
        select(monkeypatch, SelectableRuntime(name, sandbox_coverage=Coverage.PROCESS))

    yield use
    monkeypatch.delenv("ABK_RUNTIME")
    reload(None)


def test_status_shows_coverage_none_where_no_backend_matches(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_backend: None,
    runtime_env: Callable[[str], None],
) -> None:
    runtime_env("covered")
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), make_installation(tmp_path, sandbox={"enabled": True}))

    shown = capsys.readouterr()
    assert any("sandbox_coverage: none" in line for line in (shown.out + shown.err).splitlines())


def test_status_shows_the_location_guards_active_where_no_backend_matches(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_backend: None,
    runtime_env: Callable[[str], None],
) -> None:
    runtime_env("claude_code")
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), make_installation(tmp_path, sandbox={"enabled": True}))

    shown = capsys.readouterr()
    lines = (shown.out + shown.err).splitlines()
    assert any("sandbox_coverage: none" in line for line in lines)
    assert not any("skipped (confined)" in line for line in lines)
    for guard in ("worktree check", "specs fence", "config text fence"):
        assert state_of(lines, guard) == ACTIVE


def test_init_writes_no_sandbox_block_and_the_workspace_is_confined(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
) -> None:
    planning = recognised_planning(tmp_path / "planning")

    assert main([*init_args(planning, app), "--yes"]) == 0

    assert "sandbox:" not in (planning / "abk.yaml").read_text()
    assert load(planning / "abk.yaml").sandbox.enabled is True
