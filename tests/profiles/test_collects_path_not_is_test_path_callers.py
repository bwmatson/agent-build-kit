"""`collects_path` is a new question; `is_test_path` keeps meaning "a test-side file" for the
push gate, verify's deploy filter and the unit-test step, so a helper module and `conftest.py`
under `tests/` stay test-side though the runner does not collect them (spec: toolchain-profiles).

The push gate is not asserted here: for python-uv `classify_paths` already labels a path under
`tests/` by its directory name, so a test of it would pass whatever predicate the gate used."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import DeployConfig, DeployRule, RepoConfig
from agent_build_kit.pipeline.verify import deploy_commands
from tests.graph.test_outside_commits_prompt import ADOPTED, FREE_SESSION, branch, drive, land
from tests.graph_driver import tick

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
def test_the_unit_test_step_lists_a_not_collected_file_among_the_tests_an_outside_commit_changed(
    tmp_path: Path, path: str
) -> None:
    repo = branch(tmp_path)
    recorder, builder, overrides = drive(tmp_path)
    tick(tmp_path, recorder, **overrides)
    land(repo, "Reword the helper", {path: "x = 1\n"}, FREE_SESSION)
    recorder.unit_test_results = [(False, "lint: nope"), (True, "")]

    tick(tmp_path, recorder, event=ADOPTED, **overrides)
    tick(tmp_path, recorder, **overrides)

    [prompt] = builder.by_step["claude:fix_checks"]
    [changed] = [line for line in prompt.splitlines() if line.startswith("Tests changed by")]
    assert not PY.collects_path(path)
    assert path in changed
