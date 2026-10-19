"""`collects_path` is a new question; `is_test_path` keeps meaning "a test-side file" for the
push gate, verify's deploy filter and the unit-test step, so a helper module and `conftest.py`
under `tests/` stay test-side though the runner does not collect them (spec: toolchain-profiles)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import DeployConfig, DeployRule, RepoConfig
from agent_build_kit.pipeline.commit_order import classify_paths
from agent_build_kit.pipeline.verify import deploy_commands

PY = profiles.get("python-uv")
NOT_COLLECTED = ["tests/integration/replay_unit_build.py", "tests/conftest.py"]


@pytest.mark.parametrize("path", NOT_COLLECTED)
def test_the_profile_keeps_a_not_collected_file_on_the_test_side(path: str) -> None:
    assert not PY.collects_path(path)
    assert PY.is_test_path(path)


@pytest.mark.parametrize("path", NOT_COLLECTED)
def test_verify_deploys_nothing_for_a_file_the_runner_does_not_collect(
    tmp_path: Path, path: str
) -> None:
    repo = RepoConfig(
        path=tmp_path,
        slug="example/platform",
        deploy=DeployConfig(rules=[DeployRule(prefix="", run=[["deploy"]])]),
    )

    assert not PY.collects_path(path)
    assert deploy_commands(repo, [path], checkout=tmp_path) == []


@pytest.mark.parametrize("path", NOT_COLLECTED)
def test_the_push_gate_classifies_a_not_collected_file_as_a_test_file(path: str) -> None:
    assert not PY.collects_path(path)
    assert classify_paths([path], PY.is_test_path) == {path: "test"}
