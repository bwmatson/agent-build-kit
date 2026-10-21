"""A build run and a track run fail when the planning repo's abk.yaml or abk.local.yaml differs
afterwards, by whatever route it was written (spec: review-policy). The fake agent writes with
Python, a program the command policy does not name."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.config import models
from agent_build_kit.pipeline.config_guard import ConfigChanged
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes import AgentRateLimited, AgentRequest
from agent_build_kit.tracks import runner
from tests.conftest import make_installation
from tests.runtimes.stand_in import StandInRuntime
from tests.tracks.test_runner import github_checkout, inst  # noqa: F401 — fixture

ORIGINAL = "repos: {}\n"


def writes(path: Path, text: str) -> Callable[[AgentRequest], None]:
    def act(request: AgentRequest) -> None:
        path.write_text(text)

    return act


def build(planning: Path, tree: Path, agent: StandInRuntime) -> str:
    return build_run(runtime=agent, planning_repo=planning, allowed_tools="Read")(
        "Implement it.", cwd=tree, model=models().implement
    )


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    root = tmp_path / "planning"
    make_installation(root)
    (root / "abk.yaml").write_text(ORIGINAL)
    (root / "abk.local.yaml").write_text("runtime: acp\n")
    return root


@pytest.mark.parametrize("name", ["abk.yaml", "abk.local.yaml"])
def test_a_build_run_that_rewrites_a_configuration_file_fails_naming_it_and_the_difference(
    tmp_path: Path, planning: Path, name: str
) -> None:
    agent = StandInRuntime(answer="built it", act=writes(planning / name, "review: {enabled: 1}\n"))

    with pytest.raises(RuntimeError) as failed:
        build(planning, tmp_path / "tree", agent)

    message = str(failed.value)
    assert name in message
    assert "+review: {enabled: 1}" in message
    assert {"abk.yaml": "-repos: {}", "abk.local.yaml": "-runtime: acp"}[name] in message


def test_a_build_run_that_deletes_or_creates_a_configuration_file_fails(
    tmp_path: Path, planning: Path
) -> None:
    (planning / "abk.local.yaml").unlink()
    agent = StandInRuntime(act=writes(planning / "abk.local.yaml", "x: 1\n"))

    with pytest.raises(RuntimeError, match=r"abk\.local\.yaml changed during the run"):
        build(planning, tmp_path / "tree", agent)


def test_a_person_editing_during_the_run_fails_it_with_a_message_that_says_so(
    tmp_path: Path, planning: Path
) -> None:
    agent = StandInRuntime(act=writes(planning / "abk.yaml", ORIGINAL + "# a person's note\n"))

    with pytest.raises(RuntimeError) as failed:
        build(planning, tmp_path / "tree", agent)

    assert "changed during the run" in str(failed.value)
    assert "requeue" in str(failed.value)


def test_a_run_that_changes_neither_file_passes_and_the_pipelines_own_writes_do_not_trip_it(
    tmp_path: Path, planning: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def pipeline_writes(request: AgentRequest) -> None:
        (planning / "runs").mkdir(exist_ok=True)
        (planning / "runs" / "units.json").write_text("[]\n")
        (planning / "abk.yaml").write_text(ORIGINAL)  # the same bytes

    agent = StandInRuntime(answer="built it", act=pipeline_writes)

    assert build(planning, tmp_path / "tree", agent) == "built it"
    assert capsys.readouterr().out == ""
    assert (planning / "abk.yaml").read_text() == ORIGINAL


def test_a_failed_run_leaves_the_changed_file_as_it_is(tmp_path: Path, planning: Path) -> None:
    agent = StandInRuntime(act=writes(planning / "abk.yaml", "changed: 1\n"))

    with pytest.raises(RuntimeError):
        build(planning, tmp_path / "tree", agent)

    assert (planning / "abk.yaml").read_text() == "changed: 1\n", "it is not restored"


def writes_then_stops(path: Path, text: str) -> Callable[[AgentRequest], None]:
    def act(request: AgentRequest) -> None:
        path.write_text(text)
        raise AgentRateLimited("usage window spent")

    return act


def test_a_build_run_that_rewrites_a_file_and_then_stops_fails_instead_of_being_parked(
    tmp_path: Path, planning: Path
) -> None:
    agent = StandInRuntime(act=writes_then_stops(planning / "abk.yaml", "review: {enabled: 1}\n"))

    with pytest.raises(ConfigChanged) as failed:
        build(planning, tmp_path / "tree", agent)

    assert "abk.yaml changed during the run" in str(failed.value)
    assert "+review: {enabled: 1}" in str(failed.value)
    assert isinstance(failed.value.__cause__, AgentRateLimited)


def test_a_run_that_stops_with_both_files_unchanged_raises_its_own_error(
    tmp_path: Path, planning: Path
) -> None:
    def stops(request: AgentRequest) -> None:
        raise AgentRateLimited("usage window spent")

    with pytest.raises(AgentRateLimited):
        build(planning, tmp_path / "tree", StandInRuntime(act=stops))


def track(inst, monkeypatch: pytest.MonkeyPatch, agent: StandInRuntime) -> int:  # noqa: F811
    github_checkout(inst.repo("app").path, "example/app")
    github_checkout(inst.repo("platform").path, "example/platform")
    monkeypatch.setattr(runner, "repo_reachable", lambda name, inst: True)
    monkeypatch.setattr(runner, "has_headroom", lambda: True)
    monkeypatch.setattr(runner, "pull_planning", lambda inst: True)
    monkeypatch.setattr(runner, "pull", lambda path, branch: True)
    monkeypatch.setattr(runner, "record_planning", lambda inst: None)
    return runner.run_track(inst, "propose", runtime=agent)


def test_a_track_run_that_rewrites_abk_yaml_fails_with_the_file_named(
    inst,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = inst.root / "abk.yaml"
    before = config.read_text() if config.exists() else ""
    agent = StandInRuntime(act=writes(config, before + "review: {enabled: true}\n"))

    assert track(inst, monkeypatch, agent) == 1

    out = capsys.readouterr().out
    assert "abk.yaml changed during the run" in out
    assert "+review: {enabled: true}" in out


def test_a_track_run_that_changes_neither_file_passes(
    inst,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    agent = StandInRuntime(act=lambda request: (inst.state_dir / "x.md").write_text("log\n"))

    assert track(inst, monkeypatch, agent) == 0

    assert "changed during the run" not in capsys.readouterr().out


def test_a_track_run_that_rewrites_abk_yaml_and_then_stops_is_reported_as_the_change(
    inst,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = inst.root / "abk.yaml"
    before = config.read_text() if config.exists() else ""
    agent = StandInRuntime(act=writes_then_stops(config, before + "review: {enabled: true}\n"))

    assert track(inst, monkeypatch, agent) == 1

    out = capsys.readouterr().out
    assert "abk.yaml changed during the run" in out
    assert "stopped — abk.yaml changed" in out, (
        "the first project's stop is the file's, not the limit"
    )
