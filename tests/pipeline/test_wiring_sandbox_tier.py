"""The agent step's sandbox policy is chosen by the tier of the step: an `[e2e-test]` step carries
the repo's `tests.e2e_sandbox` lists, and any other step carries none of them (spec:
sandbox-e2e-policy)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.config import models
from agent_build_kit.installation import load_installation
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes import AgentRequest
from tests.pipeline.test_wiring_sandbox import Recording, install


def step(root: Path, main: Path, tier: TestTier) -> AgentRequest:
    document = yaml.safe_load((root / "abk.yaml").read_text())
    document["repos"]["app"]["tests"] = {
        "e2e_sandbox": {"hosts": ["registry.example.test"], "ports": [5432]}
    }
    (root / "abk.yaml").write_text(yaml.safe_dump(document))
    load_installation(root / "abk.yaml").activate()
    runtime = Recording()
    options: dict[str, Any] = {"sandbox_tier": tier}
    build_run(runtime=runtime, planning_repo=root, sandbox_repo="app", **options)(
        "Go.", cwd=main, model=models().implement
    )
    (request,) = runtime.requests
    return request


def test_an_e2e_step_carries_the_repo_s_e2e_lists(tmp_path: Path) -> None:
    root, main = install(tmp_path, enabled=True)

    request = step(root, main, TestTier.E2E_TEST)

    assert request.policy is not None and request.policy.sandbox is not None
    assert request.policy.sandbox.ports == (5432,)
    assert "registry.example.test" in request.policy.sandbox.hosts


@pytest.mark.parametrize("tier", [TestTier.UNIT_TEST, TestTier.INTEGRATION_TEST])
def test_any_other_step_carries_none_of_them(tmp_path: Path, tier: TestTier) -> None:
    root, main = install(tmp_path, enabled=True)

    request = step(root, main, tier)

    assert request.policy is not None and request.policy.sandbox is not None
    assert request.policy.sandbox.ports == ()
    assert "registry.example.test" not in request.policy.sandbox.hosts
