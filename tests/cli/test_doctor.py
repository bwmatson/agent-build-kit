"""`abk doctor` against recorded answers from git, gh and the OpenSpec CLI."""

from __future__ import annotations

import re
import socket
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from agent_build_kit import __version__, forges, skills
from agent_build_kit.cli import doctor, main
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import DeployConfig, DeployRule, RepoConfig, WorkspaceConfig, dump, load
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.init.scaffold import RULES_VERSION, render_openspec_config
from agent_build_kit.runtimes import AgentRateLimited, PolicyReport
from agent_build_kit.settings import reload, settings
from tests.factories import git, init_repo
from tests.forges.mock_host import MockHost, ok, recorded
from tests.runtimes.selectable import SelectableRuntime, select


class Answers:
    """A subprocess.run stand-in: gh and npx are answered here, git is real."""

    def __init__(
        self,
        *,
        owners: set[str] | None = None,
        openspec_ok: bool = True,
        scheduled: bool = True,
    ):
        self.owners = {"example"} if owners is None else owners
        self.openspec_ok = openspec_ok
        self.scheduled = scheduled
        self.commands: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if argv[:3] == ["systemctl", "--user", "is-enabled"]:
            return subprocess.CompletedProcess(
                argv,
                0 if self.scheduled else 1,
                "enabled\n" if self.scheduled else "disabled\n",
                "",
            )
        if argv[0] == "gh":
            owner = argv[-1]
            ok = owner in self.owners
            return subprocess.CompletedProcess(argv, 0 if ok else 1, "tok\n" if ok else "", "")
        if argv[0] == "npx":
            if self.openspec_ok:
                return subprocess.CompletedProcess(argv, 0, "1.0.0\n", "")
            return subprocess.CompletedProcess(argv, 1, "", "npx: command not found")
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")


def which_all(name: str) -> str | None:
    return f"/usr/bin/{name}"


def checkout(path: Path, *, email: bool = True) -> Path:
    repo = init_repo(path)
    if not email:
        git(repo, "config", "--unset", "user.email")
    return repo


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A planning repo with abk.yaml, config.yaml with our rules, skills, and
    two healthy checkouts."""
    planning = init_repo(tmp_path / "planning")
    app = checkout(tmp_path / "app")
    (app / "api").mkdir()
    (app / "api" / "Dockerfile").write_text("FROM scratch\n")
    platform = checkout(tmp_path / "platform")
    config = WorkspaceConfig(
        repos={
            "platform": RepoConfig(path=platform, slug="example/platform"),
            "app": RepoConfig(
                path=app,
                slug="example/app",
                consumes=["platform"],
                deploy={"rules": [DeployRule(prefix="api/")]},
            ),
        }
    )
    (planning / "abk.yaml").write_text(dump(config))
    (planning / "openspec").mkdir()
    (planning / "openspec" / "config.yaml").write_text(render_openspec_config(config))
    skills.install(planning / ".claude" / "skills")
    return planning


def by_name(checks: list[Check]) -> dict[str, Check]:
    return {check.name: check for check in checks}


def test_a_healthy_workspace_is_all_ok(workspace: Path) -> None:
    checks = run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all)

    assert {check.status for check in checks} <= {"ok", "info"}, [
        c for c in checks if c.status not in ("ok", "info")
    ]
    names = by_name(checks)
    assert "repo app" in names and "forge app" in names and "openspec" in names
    assert "rules" in names and "abk.yaml app" in names


def test_a_missing_config_is_the_only_check(tmp_path: Path) -> None:
    checks = run_doctor(tmp_path / "nope" / "abk.yaml", run=Answers(), which=which_all)

    assert [c.status for c in checks] == ["FAIL"]
    assert "abk init" in checks[0].fix


def test_a_worktree_root_inside_the_planning_repo_fails(workspace: Path) -> None:
    text = (workspace / "abk.yaml").read_text()
    (workspace / "abk.yaml").write_text(f"planning:\n  worktree_root: {workspace}/wt\n{text}")

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["worktree root"].status == "FAIL"


def test_repo_problems(workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolated from whoever's machine this runs on: with a global identity in
    # scope the repo has one, and the check would pass here and fail in CI.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-config"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "no-system-config"))
    git(tmp_path / "app", "config", "--unset", "user.email")
    git(tmp_path / "app", "config", "--unset", "user.name")
    text = (
        (workspace / "abk.yaml")
        .read_text()
        .replace(str(tmp_path / "platform"), str(tmp_path / "gone"))
    )
    (workspace / "abk.yaml").write_text(text)

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["repo app"].status == "FAIL"
    assert "user.email" in checks["repo app"].detail
    assert "attributed to nobody" in checks["repo app"].detail
    assert checks["repo platform"].status == "FAIL"
    assert "does not exist" in checks["repo platform"].detail


def test_a_repo_whose_host_will_not_answer_fails(workspace: Path) -> None:
    """Named per repo, not per account: the question is whether the pipeline
    can act on this repo, which is the same question on every host."""
    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(owners=set()), which=which_all))

    assert checks["forge app"].status == "FAIL"
    assert "gh auth login" in checks["forge app"].fix


def test_node_and_openspec(workspace: Path) -> None:
    checks = by_name(
        run_doctor(workspace / "abk.yaml", run=Answers(openspec_ok=False), which=lambda name: None)
    )

    assert checks["node"].status == "FAIL"
    assert checks["openspec"].status == "FAIL"


def test_ssh_key_and_verify_env(workspace: Path, tmp_path: Path) -> None:
    (tmp_path / "stack.env").write_text("TOKEN=secret-value\n")
    config = load(workspace / "abk.yaml")
    app = config.repos["app"].model_copy(
        update={
            "deploy": DeployConfig(ssh_key=tmp_path / "no.key", rules=[DeployRule(prefix="api/")])
        }
    )
    env = {
        "TOKEN": {"from": "env-file", "file": str(tmp_path / "stack.env"), "key": "TOKEN"},
        "MISSING": {"from": "env-file", "file": str(tmp_path / "stack.env"), "key": "NOPE"},
        "CMD": {"from": "command", "argv": ["true"]},
    }
    data = config.model_dump(by_alias=True, mode="json")
    data["repos"]["app"] = app.model_dump(by_alias=True, mode="json")
    data["verify"] = {"env": env}
    (workspace / "abk.yaml").write_text(dump(WorkspaceConfig.model_validate(data)))

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["ssh key app"].status == "FAIL"
    assert checks["verify.env TOKEN"].status == "ok"
    assert checks["verify.env MISSING"].status == "FAIL"
    assert checks["verify.env CMD"].status == "ok"
    assert "secret-value" not in "\n".join(f"{c.detail} {c.fix}" for c in checks.values())


def test_rules_at_the_current_version_are_ok_however_they_are_worded(workspace: Path) -> None:
    """An installation is meant to reword these rules for its own repos and
    conventions. Comparing the text flagged every such rewrite as drift; the
    stamp is what says whether the rules predate the framework's current set."""
    path = workspace / "openspec" / "config.yaml"
    text = path.read_text()
    body = text[text.index("rules:") :]
    path.write_text(
        f"# abk-rules: v{RULES_VERSION}\nschema: spec-driven\n\n"
        + re.sub(r"^    - .*$", "    - a rule of my own wording", body, flags=re.M)
    )

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["rules"].status == "ok"
    assert f"v{RULES_VERSION}" in checks["rules"].detail


def test_rules_with_no_stamp_are_unknown_rather_than_wrong(workspace: Path) -> None:
    """A config.yaml written before the stamp existed, or by hand. Nothing can
    be concluded from it, so it is reported as unknown, not as a problem."""
    path = workspace / "openspec" / "config.yaml"
    path.write_text(path.read_text().replace(f"# abk-rules: v{RULES_VERSION}\n", ""))

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["rules"].status == "info"
    assert "no `# abk-rules:` stamp" in checks["rules"].detail
    assert f"v{RULES_VERSION}" in checks["rules"].fix


def test_rules_older_than_the_framework_warn_with_what_changed(
    workspace: Path, monkeypatch
) -> None:
    from agent_build_kit.cli import doctor as doctor_module

    monkeypatch.setattr(doctor_module, "RULES_VERSION", RULES_VERSION + 2)
    monkeypatch.setattr(
        doctor_module,
        "RULES_CHANGES",
        {RULES_VERSION + 1: ["an acceptance group ends every change"], RULES_VERSION + 2: ["b"]},
    )

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["rules"].status == "warn"
    assert "an acceptance group ends every change" in checks["rules"].detail
    assert "b" in checks["rules"].detail
    assert f"v{RULES_VERSION + 2}" in checks["rules"].fix


def test_rules_newer_than_the_framework_say_to_upgrade(workspace: Path, monkeypatch) -> None:
    from agent_build_kit.cli import doctor as doctor_module

    monkeypatch.setattr(doctor_module, "RULES_VERSION", RULES_VERSION - 1)

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["rules"].status == "warn"
    assert "upgrade" in checks["rules"].fix


def test_information_is_not_a_warning_and_does_not_fail_the_run(
    workspace: Path, monkeypatch, capsys
) -> None:

    monkeypatch.setattr(
        doctor,
        "run_doctor",
        lambda path, **kw: [
            Check(name="a", status="ok", detail="fine"),
            Check(name="rules", status="info", detail="unknown", fix="stamp it"),
        ],
    )

    code = main(["--config", str(workspace / "abk.yaml"), "doctor"])

    assert code == 0
    out = capsys.readouterr().out
    assert "info  rules: unknown" in out
    assert "0 failed, 0 warning(s), 1 note(s)" in out


def test_abk_yaml_gaps(workspace: Path, tmp_path: Path) -> None:
    app = tmp_path / "app"
    (app / "worker").mkdir()
    (app / "worker" / "pyproject.toml").write_text("")
    (app / "api" / "Dockerfile").unlink()
    (app / "api").rmdir()
    (app / "scripts").mkdir()
    (app / "scripts" / "dev-stack.sh").write_text("#!/bin/bash\n")
    text = (
        (workspace / "abk.yaml")
        .read_text()
        .replace("      - prefix: api/\n", "      - prefix: api/\n      live_written: [data/]\n")
    )
    (workspace / "abk.yaml").write_text(text)

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    detail = checks["abk.yaml app"].detail
    assert checks["abk.yaml app"].status == "warn"
    assert "service dir worker/ has no deploy rule" in detail
    assert "prefix api/ no longer exists" in detail
    assert "dev_stack" in detail
    assert "live_written path data/ is not a directory" in detail
    assert checks["abk.yaml platform"].status == "ok"


def test_stale_skills_warn(workspace: Path, tmp_path: Path) -> None:
    app = tmp_path / "app"
    skill = app / ".claude" / "skills" / "abk-config" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: abk-config\ngeneratedBy: agent-build-kit 0.0.1\n---\n")

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["skills app"].status == "warn"
    assert f"older than {__version__}" in checks["skills app"].detail
    assert f"abk install-skills --repo {app}" == checks["skills app"].fix
    assert "skills planning" not in checks


def test_the_command_prints_and_exits_one_on_a_failure(
    workspace: Path, monkeypatch, capsys
) -> None:

    monkeypatch.setattr(
        doctor,
        "run_doctor",
        lambda path, **kw: [Check(name="x", status="FAIL", detail="d", fix="f")],
    )

    code = main(["--config", str(workspace / "abk.yaml"), "doctor"])

    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL  x: d" in out
    assert "fix: f" in out
    assert "1 failed" in out


def test_a_library_member_needs_no_deploy_rule_of_its_own(workspace: Path, tmp_path: Path) -> None:
    """A change in it redeploys the members that depend on it (verify's
    convention), so doctor does not ask for a rule it would never use."""
    app = tmp_path / "app"
    (app / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["lib", "api"]\n')
    (app / "lib").mkdir()
    (app / "lib" / "pyproject.toml").write_text('[project]\nname = "lib"\n')
    (app / "api" / "pyproject.toml").write_text('[project]\nname = "api"\ndependencies = ["lib"]\n')

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["abk.yaml app"].status == "ok", checks["abk.yaml app"].detail


# --- the agent runtime -------------------------------------------------------------------

UNENFORCED = PolicyReport(
    ok=False, unenforced=("merging a pull request", "pushing to a default branch")
)


def select_runtime(workspace: Path, name: str, entry: str = "") -> None:
    """Name `name` as the workspace's runtime, with its `runtimes:` entry."""
    text = (workspace / "abk.yaml").read_text() + f"runtime: {name}\n"
    if entry:
        text += f"runtimes:\n  {name}:\n{entry}"
    (workspace / "abk.yaml").write_text(text)


def test_the_active_runtime_is_reported(workspace: Path) -> None:
    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["runtime"].status == "ok"
    assert "claude_code" in checks["runtime"].detail
    assert checks["runtime coverage"].status == "ok"
    assert checks["runtime policy"].status == "ok"


def test_a_runtime_whose_agent_is_not_on_path_fails(workspace: Path) -> None:
    checks = by_name(
        run_doctor(
            workspace / "abk.yaml",
            run=Answers(),
            which=lambda name: None if name == "claude" else f"/usr/bin/{name}",
        )
    )

    assert checks["runtime"].status == "FAIL"
    assert "claude" in checks["runtime"].detail


def test_a_configured_agent_command_that_does_not_resolve_fails(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("spawned", requires=("command",)))
    select_runtime(workspace, "spawned", "    command: [some-agent, acp]\n")

    checks = by_name(
        run_doctor(
            workspace / "abk.yaml",
            run=Answers(),
            which=lambda name: None if name == "some-agent" else f"/usr/bin/{name}",
        )
    )

    assert checks["runtime"].status == "FAIL"
    assert "some-agent" in checks["runtime"].detail


def test_claude_code_s_configured_command_is_the_binary_checked(workspace: Path) -> None:
    """The one the adapter spawns in place of `claude`, so doctor checks
    what every run actually starts."""
    select_runtime(workspace, "claude_code", "    command: [/opt/agent-wrapper]\n")

    found = by_name(
        run_doctor(
            workspace / "abk.yaml",
            run=Answers(),
            which=lambda name: None if name == "claude" else f"/usr/bin/{name}",
        )
    )
    missing = by_name(
        run_doctor(
            workspace / "abk.yaml",
            run=Answers(),
            which=lambda name: None if name == "/opt/agent-wrapper" else f"/usr/bin/{name}",
        )
    )

    assert found["runtime"].status == "ok"
    assert "/opt/agent-wrapper" in found["runtime"].detail
    assert missing["runtime"].status == "FAIL"
    assert "/opt/agent-wrapper" in missing["runtime"].detail


def test_a_runtime_that_is_not_implemented_fails(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("planned", implemented=False))
    select_runtime(workspace, "planned")

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["runtime"].status == "FAIL"
    assert "planned" in checks["runtime"].detail
    assert "not implemented" in checks["runtime"].detail


def test_the_acp_runtime_is_checked_rather_than_called_not_implemented(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_build_kit.runtimes import acp

    probed: list[object] = []

    def checked(runtime, root, *, cache):
        probed.append(runtime)
        return PolicyReport(ok=True)

    monkeypatch.setattr(doctor.policy_check, "checked", checked)
    select_runtime(workspace, "acp", "    command: [some-agent, acp]\n")

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["runtime"].status == "ok"
    assert "not implemented" not in checks["runtime"].detail
    assert probed == [acp.RUNTIME]
    assert checks["runtime policy"].status == "ok"


def test_coverage_short_of_every_call_is_called_out(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("flagged", policy_coverage="agent_flagged"))
    select_runtime(workspace, "flagged")

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["runtime coverage"].status == "warn"
    assert "agent_flagged" in checks["runtime coverage"].detail


def test_an_unenforced_class_fails_naming_it_and_printing_the_installation_s_fix(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("loose", reports=(UNENFORCED,)))
    select_runtime(workspace, "loose", "    policy_fix: [scripts/constrain-agent.sh, --strict]\n")

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    policy = checks["runtime policy"]
    assert policy.status == "FAIL"
    assert "merging a pull request" in policy.detail
    assert "pushing to a default branch" in policy.detail
    assert "scripts/constrain-agent.sh --strict" in policy.fix


def test_the_policy_check_is_not_rerun_within_its_window(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = select(monkeypatch, SelectableRuntime("probed", reports=(UNENFORCED,)))
    select_runtime(workspace, "probed")

    run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all)
    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert len(runtime.checked) == 1
    assert checks["runtime policy"].status == "FAIL"


@pytest.fixture
def settings_restored():
    """Put back the settings a planning `.env` loaded."""
    yield
    reload(None)


@pytest.mark.usefixtures("settings_restored")
def test_an_unknown_runtime_the_planning_env_selects_is_a_failed_check(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selected in the planning repo's `.env` and run from elsewhere, it is
    still reported rather than raised."""
    (workspace / ".env").write_text("ABK_RUNTIME=nonesuch\n")
    monkeypatch.chdir(tmp_path)

    checks = run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all)

    failed = [check for check in checks if check.status == "FAIL"]
    assert [check.name for check in failed] == ["config"]
    assert "nonesuch" in failed[0].detail


def test_an_agent_that_cannot_start_is_not_asked_about_policy(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = select(monkeypatch, SelectableRuntime("spawned", agent_command=("some-agent",)))
    select_runtime(workspace, "spawned")

    checks = by_name(
        run_doctor(
            workspace / "abk.yaml",
            run=Answers(),
            which=lambda name: None if name == "some-agent" else f"/usr/bin/{name}",
        )
    )

    assert checks["runtime"].status == "FAIL"
    assert runtime.checked == []
    assert checks["runtime policy"].status != "ok"
    assert "some-agent" in checks["runtime policy"].detail


class _Limited(SelectableRuntime):
    """A runtime whose policy probe is refused for want of usage."""

    def check_policy(self, cwd: Path) -> PolicyReport:
        self.checked.append(cwd)
        raise AgentRateLimited("usage window exhausted")


def test_a_policy_check_that_raises_is_a_failed_check_and_not_kept(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = select(monkeypatch, _Limited("limited"))
    select_runtime(workspace, "limited")

    first = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))
    run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all)

    assert first["runtime policy"].status == "FAIL"
    assert "usage window exhausted" in first["runtime policy"].detail
    # Nothing was kept, so the second run asked again.
    assert len(runtime.checked) == 2


def test_a_default_branch_nothing_guards_is_reported(workspace: Path) -> None:
    """Worth reading in the report rather than merely being true: with no
    branch protection, the command policy hook is the only thing between an
    agent and merging its own PR. Reported, not warned about — a free private
    repo cannot have protection, and a permanent warning is one people learn
    to skip past."""
    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["merge guard app"].status == "info"
    assert "main" in checks["merge guard app"].detail
    assert "hook" in checks["merge guard app"].fix


def test_a_protected_default_branch_is_not_a_warning(workspace: Path) -> None:
    forges.register(GitHubForge(http=MockHost(ok({"required_pull_request_reviews": {}}))))
    forges.register(GitHubForge(http=MockHost(ok({"required_pull_request_reviews": {}}))))

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["merge guard app"].status == "ok"


# --- the pipeline's timers -----------------------------------------------------------
#
# Installed-but-not-enabled is the failure that looks most like success: the
# units are there, `abk status` answers perfectly, and no tick has happened in
# a week. The doctor is where that gets said out loud.


def installed_timers(workspace: Path, tmp_path: Path) -> Path:
    from agent_build_kit import timers

    units = tmp_path / "units"
    timers.install(workspace, dest=units, run=lambda *a, **k: subprocess.CompletedProcess(a, 0))
    return units


def timer_check(workspace: Path, units: Path, **answers) -> Check:
    checks = by_name(
        run_doctor(workspace / "abk.yaml", run=Answers(**answers), which=which_all, units=units)
    )
    return checks["timers"]


def test_no_timers_installed_is_worth_knowing_not_a_problem(
    workspace: Path, tmp_path: Path
) -> None:
    """Something else may run `abk tick` — cron, a CI job, a person — so the
    absence of systemd units is not a fault, only a thing to say."""
    check = timer_check(workspace, tmp_path / "none")

    assert check.status == "info"
    assert "abk install-timers" in check.fix


def test_installed_and_enabled_timers_are_ok(workspace: Path, tmp_path: Path) -> None:
    check = timer_check(workspace, installed_timers(workspace, tmp_path))

    assert check.status == "ok"
    assert str(workspace) in check.detail


def test_timers_that_are_installed_but_not_enabled_warn(workspace: Path, tmp_path: Path) -> None:
    """The one that looks like success."""
    check = timer_check(workspace, installed_timers(workspace, tmp_path), scheduled=False)

    assert check.status == "warn"
    assert "not enabled" in check.detail
    assert "abk install-timers" in check.fix


def test_a_unit_that_no_longer_matches_the_template_warns(workspace: Path, tmp_path: Path) -> None:
    from agent_build_kit import timers

    units = installed_timers(workspace, tmp_path)
    (units / timers.unit_names(workspace)[0]).write_text(
        f"{timers.MARKER}\nWorkingDirectory={workspace.resolve()}\nold\n"
    )

    check = timer_check(workspace, units)

    assert check.status == "warn"
    assert "out of date" in check.detail


def test_a_missing_unit_warns(workspace: Path, tmp_path: Path) -> None:
    from agent_build_kit import timers

    units = installed_timers(workspace, tmp_path)
    (units / timers.unit_names(workspace)[2]).unlink()

    check = timer_check(workspace, units)

    assert check.status == "warn"
    assert "missing" in check.detail


def test_units_an_earlier_version_left_behind_are_named(workspace: Path, tmp_path: Path) -> None:
    """Reinstalling removes them, and the doctor says so rather than leaving a
    person to wonder why the tick seems to run twice."""
    from tests.test_timers import legacy_units

    units = installed_timers(workspace, tmp_path)
    legacy_units(units, workspace)

    check = timer_check(workspace, units)

    assert check.status == "warn"
    assert "outdated" in check.detail and "abk-tick.service" in check.detail
    assert "removes" in check.fix


def test_a_unit_pointing_at_a_directory_that_is_gone_is_reported(
    workspace: Path, tmp_path: Path
) -> None:
    """Nobody is left to remove it: the repo it served moved away. It fails
    every five minutes and `systemctl enable` accepted it without complaint."""
    from tests.test_timers import legacy_units

    units = installed_timers(workspace, tmp_path)
    legacy_units(units, tmp_path / "moved-away")

    checks = by_name(
        run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all, units=units)
    )

    assert checks["stale timer units"].status == "warn"
    assert "moved-away" in checks["stale timer units"].detail
    assert "systemctl --user disable --now" in checks["stale timer units"].fix


def test_systemd_that_cannot_be_asked_is_said_not_assumed(workspace: Path, tmp_path: Path) -> None:
    """No `systemctl` (a container, another OS): whether the timers are enabled
    cannot be told from here, which is not the same as their being off."""
    units = installed_timers(workspace, tmp_path)

    def no_systemd(argv, **kwargs):
        if argv[0] == "systemctl":
            raise FileNotFoundError("systemctl")
        return Answers()(argv, **kwargs)

    checks = by_name(
        run_doctor(workspace / "abk.yaml", run=no_systemd, which=which_all, units=units)
    )

    assert checks["timers"].status == "info"
    assert "cannot ask systemd" in checks["timers"].detail


# --- the git: section -----------------------------------------------------------


# --- usage limits that moved ---------------------------------------------------


def test_the_new_usage_keys_are_not_warned_about(workspace: Path) -> None:
    path = workspace / "abk.yaml"
    path.write_text(
        path.read_text()
        + "runtimes:\n  claude_code:\n    limits:\n"
        + "      session:\n        usage_pause_pct: 85\n"
        + "      weekly:\n        usage_pause_pct: 90\n"
    )

    checks = run_doctor(path, run=Answers(), which=which_all)

    assert not [c for c in checks if c.name == "usage limits"]
    assert all(c.status != "FAIL" for c in checks if c.name == "config")


TELEMETRY_ENV = (
    "ABK_OTEL_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
)


@pytest.fixture
def telemetry_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    """Set telemetry settings through the environment and re-read them."""
    for key in TELEMETRY_ENV:
        monkeypatch.delenv(key, raising=False)

    def apply(**env: str) -> None:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        reload(None)

    reload(None)
    yield apply
    monkeypatch.undo()
    reload(None)


@pytest.fixture
def listening() -> Iterator[str]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(4)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"


@pytest.fixture
def closed() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


def telemetry_checks(workspace: Path) -> dict[str, Check]:
    checks = run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all)
    assert not [c for c in checks if c.status == "FAIL"]
    return {name: check for name, check in by_name(checks).items() if name.startswith("telemetry")}


def test_telemetry_is_not_checked_while_the_switch_is_off(workspace: Path, telemetry_env) -> None:
    telemetry_env(OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:9")

    assert telemetry_checks(workspace) == {}


def test_telemetry_with_no_endpoint_warns_per_signal_naming_the_variable(
    workspace: Path, telemetry_env
) -> None:
    telemetry_env(ABK_OTEL_ENABLED="true")

    checks = telemetry_checks(workspace)

    assert set(checks) == {"telemetry traces", "telemetry metrics"}
    assert {c.status for c in checks.values()} == {"warn"}
    assert "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT" in checks["telemetry traces"].fix
    assert "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT" in checks["telemetry metrics"].fix


def test_telemetry_with_an_endpoint_that_does_not_answer_warns(
    workspace: Path, telemetry_env, closed: str
) -> None:
    telemetry_env(ABK_OTEL_ENABLED="true", OTEL_EXPORTER_OTLP_ENDPOINT=closed)

    checks = telemetry_checks(workspace)

    assert {c.status for c in checks.values()} == {"warn"}
    assert all("does not answer" in c.detail for c in checks.values())


def test_telemetry_with_a_listening_endpoint_is_ok(
    workspace: Path, telemetry_env, listening: str
) -> None:
    telemetry_env(ABK_OTEL_ENABLED="true", OTEL_EXPORTER_OTLP_ENDPOINT=listening)

    checks = telemetry_checks(workspace)

    assert set(checks) == {"telemetry traces", "telemetry metrics"}
    assert {c.status for c in checks.values()} == {"ok"}


@pytest.mark.parametrize(
    "endpoint",
    ["http://127.0.0.1:99999", "http://localhost:43l8", "localhost:4318", "ftp://127.0.0.1:21"],
)
def test_telemetry_with_a_malformed_endpoint_warns_instead_of_raising(
    workspace: Path, telemetry_env, endpoint: str
) -> None:
    telemetry_env(ABK_OTEL_ENABLED="true", OTEL_EXPORTER_OTLP_ENDPOINT=endpoint)

    checks = telemetry_checks(workspace)

    assert set(checks) == {"telemetry traces", "telemetry metrics"}
    assert {c.status for c in checks.values()} == {"warn"}
    assert all("not a valid http(s) URL" in c.detail for c in checks.values())


def test_a_per_signal_endpoint_overrides_the_shared_one(
    workspace: Path, telemetry_env, listening: str, closed: str
) -> None:
    telemetry_env(
        ABK_OTEL_ENABLED="true",
        OTEL_EXPORTER_OTLP_ENDPOINT=closed,
        OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=listening,
    )

    checks = telemetry_checks(workspace)

    assert checks["telemetry traces"].status == "ok"
    assert checks["telemetry metrics"].status == "warn"


def _github_account() -> httpx.BaseTransport:
    """GitHub answering GET /user as the account `example-bot`, as recorded."""
    return MockHost(recorded("user_200"))


@pytest.fixture
def logged_out_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_credentials()
    monkeypatch.setattr(settings, "gh_token", "")


def test_doctor_without_a_transport_asks_the_substituted_host(
    workspace: Path, logged_out_settings: None
) -> None:
    """The suite's conftest puts the recorded account where GitHub would be, so
    a caller that passes no `transport` never reaches the network."""
    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert "example-bot" in checks["forge app"].detail


def test_doctor_reports_the_account_each_repo_credential_acts_as(
    workspace: Path, logged_out_settings: None
) -> None:
    checks = by_name(
        run_doctor(
            workspace / "abk.yaml",
            run=Answers(),
            which=which_all,
            transport=_github_account(),
        )
    )

    assert checks["forge app"].status == "ok"
    assert "example-bot" in checks["forge app"].detail
    assert "example-bot" in checks["forge platform"].detail


def test_doctor_on_a_logged_out_machine_names_the_sources_tried(
    workspace: Path, logged_out_settings: None
) -> None:
    checks = by_name(
        run_doctor(
            workspace / "abk.yaml",
            run=Answers(owners=set()),
            which=which_all,
            transport=_github_account(),
        )
    )

    assert checks["forge app"].status == "FAIL"
    text = f"{checks['forge app'].detail} {checks['forge app'].fix}"
    assert "GH_TOKEN" in text
    assert "gh auth token --user example" in text


@pytest.mark.parametrize("answer", ["rate_limit_429", "repo_404"])
def test_doctor_reports_a_failing_account_call_as_a_failure_naming_the_source(
    workspace: Path,
    logged_out_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    monkeypatch.setattr(settings, "forge_retries", 0)

    checks = by_name(
        run_doctor(
            workspace / "abk.yaml",
            run=Answers(),
            which=which_all,
            transport=MockHost(recorded(answer)),
        )
    )

    assert checks["forge app"].status == "FAIL"
    assert "gh auth token --user example" in checks["forge app"].detail
