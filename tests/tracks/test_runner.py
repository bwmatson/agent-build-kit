"""The track runner against a temporary installation.

Two properties carried over from before the runner took an `Installation`:

- **It doesn't start a track with no room in the session window.** A timer
  fires whether or not there is headroom, and an account with credits enabled
  spends real money past the window rather than queueing.
- **`implement` carries no dollar budget.** The window is the limit;
  `usage_guard` reads it live. A guessed dollar ceiling beside that drifts
  from real cost, and set too low it refuses to start a run instead of
  bounding one.

Everything else here is the new surface: paths derived from the
installation, placeholders rendered from abk.yaml, eligibility, and dry runs.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import tracks as tracks_cli
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_guard import Decision, UsageReading
from agent_build_kit.tracks import runner
from tests.factories import git, init_repo

PLACEHOLDER = re.compile(r"__[A-Z_]+__")


def reading(**overrides) -> UsageReading:
    defaults: dict = {
        "session_pct": 10,
        "weekly_pct": 10,
        "resets_at": datetime.now(UTC) + timedelta(hours=2),
        "observed_at": datetime.now(UTC),
        "source": "live",
        "credits_enabled": True,
        "credits_used_dollars": 0.0,
        "spend_limit_reached": False,
    }
    return UsageReading(**{**defaults, **overrides})


def make_installation(root: Path, **overrides) -> Installation:
    """`app` (which consumes `platform`) and `platform`, checked out under
    `root/checkouts`, with the descriptions the prompts render."""
    config = WorkspaceConfig.model_validate(
        {
            "repos": {
                "platform": {
                    "path": str(root / "checkouts" / "platform"),
                    "slug": "example/platform",
                    "description": "The platform every other repo builds on.",
                },
                "app": {
                    "path": str(root / "checkouts" / "app"),
                    "slug": "example/app",
                    "description": "The application.",
                    "consumes": ["platform"],
                    "default_branch": "trunk",
                },
            },
            **overrides,
        }
    )
    root.mkdir(parents=True, exist_ok=True)
    return Installation(config, root)


def github_checkout(path: Path, slug: str) -> Path:
    init_repo(path)
    git(path, "remote", "add", "origin", f"git@github.com:{slug}.git")
    return path


def project(inst: Installation, name: str = "app") -> runner.Project:
    repo = inst.repo(name)
    return runner.Project(
        name=name,
        path=repo.path,
        repo=repo.slug,
        default_branch=repo.default_branch,
        description=repo.description,
        consumes=list(repo.consumes),
    )


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(tmp_path / "planning")


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Captures every claude command instead of running it; a run succeeds
    with empty JSON."""
    captured: list[list[str]] = []

    def record(cmd, **kwargs) -> subprocess.CompletedProcess:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(runner, "run_phase_command", record)
    return captured


# --- budgets and headroom -------------------------------------------------------


def test_implement_runs_without_a_dollar_budget(inst, recorder) -> None:
    """The session window is what bounds it."""
    runner.implement(inst, project(inst))

    assert "--max-budget-usd" not in recorder[0]


def test_a_phase_honours_the_configured_budget(tmp_path, recorder) -> None:
    inst = make_installation(tmp_path, tracks={"budgets_usd": {"health": 4.25}})

    runner.health(inst, project(inst))

    cmd = recorder[0]
    assert cmd[cmd.index("--max-budget-usd") + 1] == "4.25"


def test_a_track_without_a_budget_entry_runs_unbounded(tmp_path, recorder) -> None:
    inst = make_installation(tmp_path, tracks={"budgets_usd": {}})

    runner.health(inst, project(inst))

    assert "--max-budget-usd" not in recorder[0]


def test_a_full_window_stops_the_run_before_any_project(monkeypatch, capsys) -> None:
    """The only thing standing between a timer and a credit charge."""
    monkeypatch.setattr(runner, "current_usage", lambda: reading(session_pct=88))
    monkeypatch.setattr(
        runner, "may_start_unit", lambda r: Decision(may_start=False, reason="session at 88%")
    )

    assert runner.has_headroom() is False
    assert "88%" in capsys.readouterr().out


def test_room_in_the_window_lets_it_run(monkeypatch) -> None:
    monkeypatch.setattr(runner, "current_usage", lambda: reading())
    monkeypatch.setattr(runner, "may_start_unit", lambda r: Decision(may_start=True, reason="ok"))

    assert runner.has_headroom() is True


# --- the claude command -----------------------------------------------------------


def test_the_command_comes_from_the_tracks_config(tmp_path, recorder) -> None:
    inst = make_installation(
        tmp_path,
        tracks={"model": "haiku", "allowed_tools": "Read", "disallowed_tools": "Bash(rm *)"},
    )

    runner.implement(inst, project(inst))

    cmd = recorder[0]
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--add-dir") + 1] == str(inst.root)
    assert cmd[cmd.index("--model") + 1] == "haiku"
    assert cmd[cmd.index("--allowedTools") + 1] == "Read"
    assert cmd[cmd.index("--disallowedTools") + 1] == "Bash(rm *)"
    assert cmd[cmd.index("--worktree") + 1] == f"abk-{runner.RUN_ID}"


def test_raw_output_lands_under_the_planning_root(tmp_path, recorder) -> None:
    inst = make_installation(tmp_path, tracks={"raw_output_dir": "raw"})

    runner.implement(inst, project(inst))

    assert (inst.root / "raw" / f"{runner.RUN_ID}-app-implement.json").read_text() == "{}"


def test_a_failed_phase_reports_and_continues(inst, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        runner,
        "run_phase_command",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 3, "", "budget exhausted"),
    )

    assert runner.implement(inst, project(inst)) == 3
    assert "exited 3" in capsys.readouterr().out


# --- run logs and health's readback ------------------------------------------------


def test_run_log_lives_in_the_state_dir(tmp_path) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "logs/runs"})

    path = runner.run_log(inst, project(inst), "health")

    assert path == inst.root / "logs" / "runs" / f"{runner.RUN_ID}-app-health.md"
    assert path == inst.state_dir / f"{runner.RUN_ID}-app-health.md"


def phases_run(inst: Installation, monkeypatch, *, status: str | None) -> list[str]:
    phases: list[str] = []

    def fake(cmd, **kwargs) -> subprocess.CompletedProcess:
        phase = Path(cmd[-1].splitlines()[0].split("—")[0].split(":")[1].strip().split()[0])
        phases.append(str(phase))
        if str(phase) == "health" and status is not None:
            log = runner.run_log(inst, project(inst), "health")
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(f"# Health\n\n**Status:** {status} — because\n")
        return subprocess.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(runner, "run_phase_command", fake)
    runner.health(inst, project(inst))
    return phases


def test_an_attention_status_runs_implement_at_once(inst, monkeypatch) -> None:
    assert phases_run(inst, monkeypatch, status="ATTENTION") == ["health", "implement"]


def test_an_ok_status_stops_after_health(inst, monkeypatch) -> None:
    assert phases_run(inst, monkeypatch, status="OK") == ["health"]


def test_pending_resolution_stops_after_health(inst, monkeypatch) -> None:
    assert phases_run(inst, monkeypatch, status="PENDING RESOLUTION") == ["health"]


def test_a_missing_run_log_does_not_trigger_implement(inst, monkeypatch, capsys) -> None:
    assert phases_run(inst, monkeypatch, status=None) == ["health"]
    assert "couldn't determine health status" in capsys.readouterr().out


def test_read_status_only_accepts_the_documented_words(tmp_path) -> None:
    path = tmp_path / "log.md"
    path.write_text("**Status:** FINE\n")
    assert runner.read_status(path) is None
    path.write_text("**Status:** URGENT — disk full\n")
    assert runner.read_status(path) == "URGENT"


def test_discovery_failure_still_runs_implement(inst, monkeypatch) -> None:
    phases: list[str] = []

    def fake(cmd, **kwargs) -> subprocess.CompletedProcess:
        name = "improve" if "improve phase" in cmd[-1].splitlines()[0] else "implement"
        phases.append(name)
        return subprocess.CompletedProcess(cmd, 1 if name == "improve" else 0, "{}", "")

    monkeypatch.setattr(runner, "run_phase_command", fake)

    assert runner.DISPATCH["improve"](inst, project(inst), None) == 1
    assert phases == ["improve", "implement"]


# --- placeholders ---------------------------------------------------------------


def test_placeholders_cover_the_documented_set(inst) -> None:
    assert set(runner.placeholders(inst, project(inst), "health")) == runner.PLACEHOLDERS


@pytest.mark.parametrize("phase", runner.PHASES)
def test_every_shipped_prompt_renders_fully(inst, phase) -> None:
    text = runner.render_prompt(inst, project(inst), phase)

    assert not PLACEHOLDER.findall(text)
    assert "`app`" in text
    assert str(inst.repo("app").path) in text
    assert "example/app" in text
    assert str(inst.root) in text
    assert str(runner.run_log(inst, project(inst), phase)) in text


def test_the_new_placeholders_render_from_the_repo_config(inst) -> None:
    values = runner.placeholders(inst, project(inst), "implement")

    assert values["__PROJECT_DESCRIPTION__"] == "The application."
    assert values["__PROJECT_CONSUMES__"] == "platform"
    assert values["__WORKSPACE_REPOS__"] == (
        "- platform — The platform every other repo builds on.\n- app — The application."
    )
    assert values["__PLANNING_DIR__"] == str(inst.root)
    assert values["__STATE_DIR__"] == str(inst.state_dir)
    assert values["__PROJECT_REPO_URL__"] == "https://github.com/example/app"
    assert values["__IMPLEMENT_MAX_PRS__"] == "3"


def test_a_repo_that_consumes_nothing_says_so(inst) -> None:
    values = runner.placeholders(inst, project(inst, "platform"), "health")

    assert values["__PROJECT_CONSUMES__"] == "nothing"


def test_prompts_dir_overrides_the_shipped_prompts(tmp_path) -> None:
    custom = tmp_path / "my-prompts"
    custom.mkdir()
    (custom / "health.md").write_text("custom for __PROJECT__ in __PROMPTS_DIR__\n")
    inst = make_installation(tmp_path / "planning", tracks={"prompts_dir": str(custom)})

    assert runner.prompts_dir(inst) == custom
    assert runner.render_prompt(inst, project(inst), "health") == f"custom for app in {custom}\n"


def test_a_relative_prompts_dir_is_under_the_planning_root(tmp_path) -> None:
    inst = make_installation(tmp_path, tracks={"prompts_dir": "prompts"})

    assert runner.prompts_dir(inst) == inst.root / "prompts"


def test_an_unknown_placeholder_is_an_error(tmp_path) -> None:
    custom = tmp_path / "my-prompts"
    custom.mkdir()
    (custom / "health.md").write_text("__NOT_A_THING__\n")
    inst = make_installation(tmp_path / "planning", tracks={"prompts_dir": str(custom)})

    with pytest.raises(ValueError, match="__NOT_A_THING__"):
        runner.render_prompt(inst, project(inst), "health")


# --- focus -------------------------------------------------------------------------


def test_focus_on_a_track_names_the_latest_run_log(inst) -> None:
    inst.state_dir.mkdir(parents=True)
    (inst.state_dir / "20260101-000000-app-improve.md").write_text("")
    (inst.state_dir / "20260102-000000-app-improve.md").write_text("")
    (inst.state_dir / "20260103-000000-platform-improve.md").write_text("")

    hint = runner.resolve_focus(inst, project(inst), "improve")

    assert hint.startswith(str(inst.state_dir / "20260102-000000-app-improve.md"))


def test_focus_on_a_run_id_prefers_the_source_track_over_its_implement_log(inst) -> None:
    inst.state_dir.mkdir(parents=True)
    (inst.state_dir / "20260101-000000-app-recommend.md").write_text("")
    (inst.state_dir / "20260101-000000-app-implement.md").write_text("")

    hint = runner.resolve_focus(inst, project(inst), "20260101-000000")

    assert hint.startswith(str(inst.state_dir / "20260101-000000-app-recommend.md"))


def test_focus_with_nothing_to_match_falls_back(inst) -> None:
    assert runner.resolve_focus(inst, project(inst), "health").startswith("none —")
    assert runner.resolve_focus(inst, project(inst), None).startswith("none —")


# --- eligibility ---------------------------------------------------------------------


def test_eligible_projects_keeps_only_github_checkouts(inst, monkeypatch, capsys) -> None:
    github_checkout(inst.repo("app").path, "example/app")
    inst.repo("platform").path.mkdir(parents=True)  # not a git checkout
    monkeypatch.setattr(runner, "repo_reachable", lambda slug: True)

    projects = runner.eligible_projects(inst)

    assert [p.name for p in projects] == ["app"]
    only = projects[0]
    assert only.repo == "example/app"
    assert only.default_branch == "trunk"
    assert only.consumes == ["platform"]
    assert only.description == "The application."
    assert "skip platform" in capsys.readouterr().out


def test_eligible_projects_skips_a_checkout_without_a_github_origin(inst, monkeypatch) -> None:
    init_repo(inst.repo("app").path)  # no origin at all
    platform = init_repo(inst.repo("platform").path)
    git(platform, "remote", "add", "origin", "https://example.org/git/platform.git")
    monkeypatch.setattr(runner, "repo_reachable", lambda slug: True)

    assert runner.eligible_projects(inst) == []


def test_eligible_projects_skips_an_origin_that_disagrees_with_the_config(
    inst, monkeypatch, capsys
) -> None:
    github_checkout(inst.repo("app").path, "someone-else/app")
    monkeypatch.setattr(runner, "repo_reachable", lambda slug: True)

    assert runner.eligible_projects(inst, "app") == []
    assert "abk.yaml says example/app" in capsys.readouterr().out


def test_eligible_projects_skips_a_repo_gh_cannot_see(inst, monkeypatch) -> None:
    github_checkout(inst.repo("app").path, "example/app")
    monkeypatch.setattr(runner, "repo_reachable", lambda slug: False)

    assert runner.eligible_projects(inst, "app") == []


def test_only_filters_by_config_key(inst, monkeypatch) -> None:
    github_checkout(inst.repo("app").path, "example/app")
    github_checkout(inst.repo("platform").path, "example/platform")
    monkeypatch.setattr(runner, "repo_reachable", lambda slug: True)

    assert [p.name for p in runner.eligible_projects(inst, "platform")] == ["platform"]


# --- pulling --------------------------------------------------------------------------


def test_self_pull_off_skips_the_planning_pull(tmp_path, monkeypatch) -> None:
    inst = make_installation(tmp_path, planning={"self_pull": False})
    monkeypatch.setattr(runner, "pull", lambda *a: pytest.fail("pulled the planning repo"))

    assert runner.pull_planning(inst) is True


def test_self_pull_on_pulls_the_default_branch(inst, monkeypatch) -> None:
    pulled: list[tuple[Path, str]] = []
    monkeypatch.setattr(runner, "pull", lambda path, branch: pulled.append((path, branch)) or True)
    monkeypatch.setattr(runner, "default_branch_of", lambda path: "develop")

    assert runner.pull_planning(inst) is True
    assert pulled == [(inst.root, "develop")]


def test_a_failed_planning_pull_is_fatal(inst, monkeypatch) -> None:
    monkeypatch.setattr(runner, "pull", lambda path, branch: False)

    assert runner.pull_planning(inst) is False


def test_default_branch_of_reads_origin_head(tmp_path) -> None:
    repo = init_repo(tmp_path / "repo")
    assert runner.default_branch_of(repo) == "main"
    git(repo, "remote", "add", "origin", "git@github.com:example/app.git")
    git(repo, "commit", "--allow-empty", "-q", "-m", "init")
    git(repo, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    assert runner.default_branch_of(repo) == "trunk"


def test_a_project_pulls_its_own_default_branch(inst, monkeypatch, recorder) -> None:
    github_checkout(inst.repo("app").path, "example/app")
    monkeypatch.setattr(runner, "repo_reachable", lambda slug: True)
    monkeypatch.setattr(runner, "has_headroom", lambda: True)
    monkeypatch.setattr(runner, "pull_planning", lambda inst: True)
    pulled: list[tuple[Path, str]] = []
    monkeypatch.setattr(runner, "pull", lambda path, branch: pulled.append((path, branch)) or True)

    assert runner.run_track(inst, "implement", only="app") == 0
    assert pulled == [(inst.repo("app").path, "trunk")]
    assert len(recorder) == 1


# --- the whole track ----------------------------------------------------------------


def test_run_track_reports_a_failed_project(inst, monkeypatch) -> None:
    github_checkout(inst.repo("app").path, "example/app")
    github_checkout(inst.repo("platform").path, "example/platform")
    monkeypatch.setattr(runner, "repo_reachable", lambda slug: True)
    monkeypatch.setattr(runner, "has_headroom", lambda: True)
    monkeypatch.setattr(runner, "pull_planning", lambda inst: True)
    monkeypatch.setattr(runner, "pull", lambda path, branch: path.name != "platform")
    monkeypatch.setattr(
        runner,
        "run_phase_command",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "{}", ""),
    )

    assert runner.run_track(inst, "implement") == 1


def test_no_headroom_ends_the_run_quietly(inst, monkeypatch) -> None:
    monkeypatch.setattr(runner, "has_headroom", lambda: False)
    monkeypatch.setattr(runner, "eligible_projects", lambda *a: pytest.fail("looked at projects"))

    assert runner.run_track(inst, "health") == 0


def test_dry_run_prints_prompts_and_commands_without_running_claude(
    inst, monkeypatch, capsys
) -> None:
    github_checkout(inst.repo("app").path, "example/app")
    monkeypatch.setattr(runner, "repo_reachable", lambda slug: True)
    monkeypatch.setattr(runner, "current_usage", lambda: pytest.fail("checked usage"))
    monkeypatch.setattr(runner, "pull", lambda *a: pytest.fail("pulled a repo"))
    monkeypatch.setattr(runner, "run_phase_command", lambda *a, **kw: pytest.fail("ran claude"))

    assert runner.run_track(inst, "improve", only="app", dry_run=True) == 0

    out = capsys.readouterr().out
    assert "# Mission: improve phase — project `app`" in out
    assert "# Mission: implement phase — project `app`" in out
    assert "claude -p" in out
    assert f"--add-dir {inst.root}" in out
    assert "'<prompt>'" in out
    assert not PLACEHOLDER.findall(out)
    assert not (inst.root / inst.config.tracks.raw_output_dir).exists()


# --- the CLI ----------------------------------------------------------------------------


def test_abk_track_dispatches_to_run_track(inst, monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        tracks_cli,
        "run_track",
        lambda inst, phase, **kw: calls.append((inst, phase, kw)) or 0,
    )
    parser = argparse.ArgumentParser()
    tracks_cli.register(parser.add_subparsers(dest="command"))

    args = parser.parse_args(
        ["track", "implement", "--project", "app", "--focus", "recommend", "--dry-run"]
    )

    assert args.func(args, inst) == 0
    assert calls == [(inst, "implement", {"only": "app", "focus": "recommend", "dry_run": True})]


def test_abk_track_rejects_an_unknown_phase() -> None:
    parser = argparse.ArgumentParser()
    tracks_cli.register(parser.add_subparsers(dest="command"))

    with pytest.raises(SystemExit):
        parser.parse_args(["track", "deploy"])
