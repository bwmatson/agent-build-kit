"""With the sandbox on by default, a step on a machine with no backend runs unconfined and says
so, and a step whose backend fails its probe stops with the cause and the fix (spec:
sandbox-default)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from agent_build_kit import sandboxes
from agent_build_kit.config import models
from agent_build_kit.installation import load_installation
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.sandboxes import unavailable
from tests.pipeline.test_wiring_sandbox import Recording, install
from tests.sandboxes.stand_in import StandInBackend

ELSEWHERE = "no-such-platform"


def machine(landlock: StandInBackend) -> None:
    """The registry of a machine whose `landlock` is `landlock` and whose `seatbelt` is for
    another platform."""
    sandboxes.register(landlock)
    sandboxes.register(StandInBackend("seatbelt", ELSEWHERE))


@pytest.fixture(autouse=True)
def registry() -> Iterator[None]:
    with sandboxes.isolated():
        yield


def run_step(tmp_path: Path, lines: list[str]) -> Recording:
    """One step of a workspace that writes no `sandbox` block."""
    root, main = install(tmp_path, enabled=True)
    document = yaml.safe_load((root / "abk.yaml").read_text())
    del document["sandbox"]
    (root / "abk.yaml").write_text(yaml.safe_dump(document))
    load_installation(root / "abk.yaml").activate()
    runtime = Recording()
    build_run(runtime=runtime, planning_repo=root, sandbox_repo="app", log=lines.append)(
        "Go.", cwd=main, model=models().implement
    )
    return runtime


def test_with_no_sandbox_block_and_a_working_backend_the_step_is_confined(
    tmp_path: Path,
) -> None:
    machine(StandInBackend("landlock", ""))

    runtime = run_step(tmp_path, [])

    (request,) = runtime.requests
    assert request.policy is not None and request.policy.sandbox is not None


def test_a_machine_with_no_backend_runs_the_step_unconfined_and_says_why_once(
    tmp_path: Path,
) -> None:
    machine(StandInBackend("landlock", ELSEWHERE))
    lines: list[str] = []

    runtime = run_step(tmp_path, lines)

    (request,) = runtime.requests
    assert request.policy is not None and request.policy.sandbox is None
    said = [line for line in lines if "unconfined" in line]
    assert len(said) == 1
    assert unavailable.CAUSE in said[0]


def test_a_backend_that_matches_the_platform_and_fails_its_probe_stops_the_step(
    tmp_path: Path,
) -> None:
    machine(StandInBackend("landlock", "", ok=False))

    with pytest.raises(RuntimeError) as stopped:
        run_step(tmp_path, [])

    assert "stand-in off" in str(stopped.value)
    assert "turn on" in str(stopped.value)
