"""A track run that changes abk.yaml or abk.local.yaml is warned about with the diff and goes on;
the track runner has nothing that stops a run for it (spec: sandbox-default)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.config_guard import warning_lines
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.sandboxes import Coverage
from agent_build_kit.tracks import runner
from tests.pipeline.test_config_unchanged_by_run import MAY_HAVE_WRITTEN, writes, writes_then_stops
from tests.runtimes.stand_in import StandInRuntime
from tests.tracks.test_runner import github_checkout, inst  # noqa: F401 — fixture


def track(inst, monkeypatch: pytest.MonkeyPatch, agent: StandInRuntime) -> int:  # noqa: F811
    github_checkout(inst.repo("app").path, "example/app")
    github_checkout(inst.repo("platform").path, "example/platform")
    monkeypatch.setattr(runner, "repo_reachable", lambda name, inst: True)
    monkeypatch.setattr(runner, "has_headroom", lambda: True)
    monkeypatch.setattr(runner, "pull_planning", lambda inst: True)
    monkeypatch.setattr(runner, "pull", lambda path, branch: True)
    monkeypatch.setattr(runner, "record_planning", lambda inst: None)
    return runner.run_track(inst, "propose", runtime=agent)


def test_a_track_run_that_rewrites_abk_yaml_warns_with_the_diff_and_goes_on(
    inst,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = inst.root / "abk.yaml"
    before = config.read_text() if config.exists() else ""
    agent = StandInRuntime(act=writes(config, before + "review: {enabled: true}\n"))

    assert track(inst, monkeypatch, agent) == 0

    out = capsys.readouterr().out
    assert "abk.yaml changed during the run" in out
    assert "+review: {enabled: true}" in out
    assert MAY_HAVE_WRITTEN in out


def test_a_track_run_that_rewrites_abk_yaml_leaves_the_warning_for_status(
    inst,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = inst.root / "abk.yaml"
    runs: list[int] = []

    def rewrite(request: AgentRequest) -> None:
        # Every project's phase changes the file, so none of them ends clean and clears the warning.
        runs.append(len(runs))
        config.write_text(f"review: {{enabled: true}}\n# run {len(runs)}\n")

    agent = StandInRuntime(act=rewrite)

    assert track(inst, monkeypatch, agent) == 0

    kept = "\n".join(warning_lines(inst.state_dir))
    assert "abk.yaml changed during the run" in kept
    assert MAY_HAVE_WRITTEN in kept


def test_a_track_run_goes_on_after_a_change_whatever_coverage_its_runtime_reports(
    inst,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = inst.root / "abk.yaml"
    before = config.read_text() if config.exists() else ""
    agent = StandInRuntime(act=writes(config, before + "review: {enabled: true}\n"))
    agent.sandbox_coverage = Coverage.PROCESS

    assert track(inst, monkeypatch, agent) == 0

    out = capsys.readouterr().out
    assert "abk.yaml changed during the run" in out
    assert "+review: {enabled: true}" in out


def test_a_track_run_that_rewrites_abk_yaml_and_then_stops_reports_the_stop_not_the_file(
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
    assert "usage window spent" in out
    assert "stopped — abk.yaml changed" not in out
