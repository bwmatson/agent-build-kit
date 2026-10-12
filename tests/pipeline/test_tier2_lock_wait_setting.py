"""How long a unit waits for the tier 2 lock is `limits.tier2_lock_wait_seconds`
(spec: tier2-lock-wait-is-configurable).

The lock is held through `flock` on the lock file, as another process would hold it, and
the clock the wait reads is replaced, so no test sleeps.
"""

from __future__ import annotations

import fcntl
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main
from agent_build_kit.cli.pipeline import StackBusy, verify_one
from agent_build_kit.config import (
    ConfigError,
    LimitsConfig,
    RepoConfig,
    WorkspaceConfig,
    dump,
    load,
)
from agent_build_kit.pipeline import tier2
from tests.conftest import make_installation

SETTING = "limits.tier2_lock_wait_seconds"


class WaitClock:
    """Stands in for the `time` module `stack_lock` reads: sleeping moves it on."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0.5)

    def strftime(self, *args):
        return time.strftime(*args)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> WaitClock:
    fake = WaitClock()
    monkeypatch.setattr(tier2, "time", fake)
    return fake


@contextmanager
def held(path: Path) -> Iterator[None]:
    """The tier 2 lock taken by someone else."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def write_yaml(tmp_path: Path, value: str) -> Path:
    path = tmp_path / "abk.yaml"
    path.write_text(f"limits:\n  tier2_lock_wait_seconds: {value}\n")
    return path


def test_the_wait_defaults_to_ninety_minutes(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text("{}\n")

    assert load(path).limits.tier2_lock_wait_seconds == 5400
    assert LimitsConfig().tier2_lock_wait_seconds == 5400


@pytest.mark.parametrize("value", ["0", "-5", "90.5", "soon"])
def test_a_value_that_cannot_be_a_wait_fails_to_load_naming_the_key(
    tmp_path: Path, value: str
) -> None:
    with pytest.raises(ConfigError) as refused:
        load(write_yaml(tmp_path, value))

    assert SETTING in str(refused.value)


def test_verify_one_uses_the_configured_wait_unless_given_its_own(
    tmp_path: Path, clock: WaitClock
) -> None:
    inst = make_installation(tmp_path, limits={"tier2_lock_wait_seconds": 9})
    waited = []

    with held(inst.state_dir / "tier2.lock"):
        for options in ({}, {"wait": 1}):
            with pytest.raises(StackBusy) as busy:
                verify_one(inst, "add-marker", [], **options)
            waited.append(str(busy.value))

    assert "waited 9s" in waited[0]
    assert "waited 1s" in waited[1]


def test_the_busy_message_names_the_setting_only_for_the_configured_wait(
    tmp_path: Path, clock: WaitClock
) -> None:
    inst = make_installation(tmp_path, limits={"tier2_lock_wait_seconds": 2})
    messages = []

    with held(inst.state_dir / "tier2.lock"):
        for options in ({}, {"wait": 0}):
            with pytest.raises(StackBusy) as busy:
                verify_one(inst, "add-marker", [], **options)
            messages.append(str(busy.value))

    assert "waited 2s" in messages[0]
    assert SETTING in messages[0]
    assert "waited 0s" in messages[1]
    assert SETTING not in messages[1]


def test_stack_lock_names_the_setting_it_is_given(tmp_path: Path, clock: WaitClock) -> None:
    lock = tmp_path / "tier2.lock"

    with held(lock), pytest.raises(TimeoutError) as busy:
        with tier2.stack_lock(lock, timeout=2, setting=SETTING):
            pass

    assert f"waited 2s for {lock} ({SETTING})" in str(busy.value)


def test_config_show_lists_the_wait_with_its_default_and_a_configured_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repos = {"app": RepoConfig(path=tmp_path / "app", slug="example/app")}
    path = tmp_path / "abk.yaml"
    path.write_text(dump(WorkspaceConfig(repos=repos)))

    main(["--config", str(path), "config", "--show"])
    default = yaml.safe_load(capsys.readouterr().out)["limits"]["tier2_lock_wait_seconds"]

    configured = WorkspaceConfig(repos=repos, limits=LimitsConfig(tier2_lock_wait_seconds=120))
    path.write_text(dump(configured))
    main(["--config", str(path), "config", "--show"])
    shown = yaml.safe_load(capsys.readouterr().out)["limits"]["tier2_lock_wait_seconds"]

    assert (default, shown) == (5400, 120)
