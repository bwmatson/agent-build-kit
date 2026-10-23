"""`build_runner` runs a unit's build under the sandbox policy of the unit's own kind: a
`[e2e-test]` unit gets the repo's `tests.e2e_sandbox` ports, any other unit gets none
(spec: sandbox-e2e-policy)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit import runtimes
from agent_build_kit.installation import load_installation
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_runner
from agent_build_kit.runtimes import AgentRequest
from tests.factories import unit
from tests.pipeline.test_wiring_sandbox import install
from tests.runtimes.stand_in import StandInRuntime


def build_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tier: TestTier) -> AgentRequest:
    # The policy reads abk.yaml itself, so the installation is loaded from a file on disk.
    root, _ = install(tmp_path, enabled=True)
    document = yaml.safe_load((root / "abk.yaml").read_text())
    document["repos"]["app"]["tests"] = {"e2e_sandbox": {"ports": [5432]}}
    (root / "abk.yaml").write_text(yaml.safe_dump(document))
    inst = load_installation(root / "abk.yaml")
    agent = StandInRuntime(answer="ok")
    monkeypatch.setattr(runtimes, "active", lambda: agent)
    runner = build_runner(
        unit(tier=tier),
        store=UnitStore(tmp_path / "units.json"),
        installation=inst,
        log=lambda _: None,
    )
    tree = tmp_path / "tree"
    tree.mkdir()

    runner.run("Implement.", cwd=tree, model="m")

    return agent.request


def test_an_e2e_test_unit_s_build_gets_the_repo_s_e2e_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = build_request(tmp_path, monkeypatch, TestTier.E2E_TEST)

    assert request.policy is not None and request.policy.sandbox is not None
    assert request.policy.sandbox.ports == (5432,)


@pytest.mark.parametrize("tier", [TestTier.UNIT_TEST, TestTier.INTEGRATION_TEST])
def test_any_other_unit_s_build_gets_no_service_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tier: TestTier
) -> None:
    request = build_request(tmp_path, monkeypatch, tier)

    assert request.policy is not None and request.policy.sandbox is not None
    assert request.policy.sandbox.ports == ()
