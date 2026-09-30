"""`abk doctor` against recorded answers from git, gh and the OpenSpec CLI."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from agent_build_kit import __version__, skills
from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import DeployConfig, DeployRule, RepoConfig, WorkspaceConfig, dump, load
from agent_build_kit.init.scaffold import RULES_VERSION, render_openspec_config
from agent_build_kit.runtimes import AgentRateLimited, PolicyReport
from agent_build_kit.settings import reload
from tests.factories import git, init_repo
from tests.runtimes.selectable import SelectableRuntime, select


class Answers:
    """A subprocess.run stand-in: gh and npx are answered here, git is real."""

    def __init__(
        self,
        *,
        owners: set[str] | None = None,
        openspec_ok: bool = True,
        protection: bool = False,
    ):
        self.owners = {"example"} if owners is None else owners
        self.openspec_ok = openspec_ok
        self.protection = protection
        self.commands: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if argv[:2] == ["gh", "api"] and argv[-1].endswith("/protection"):
            body = '{"required_pull_request_reviews": {}}' if self.protection else ""
            return subprocess.CompletedProcess(argv, 0 if self.protection else 1, body, "")
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


def test_repo_problems(workspace: Path, tmp_path: Path) -> None:
    git(tmp_path / "app", "config", "--unset", "user.email")
    text = (
        (workspace / "abk.yaml")
        .read_text()
        .replace(str(tmp_path / "platform"), str(tmp_path / "gone"))
    )
    (workspace / "abk.yaml").write_text(text)

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["repo app"].status == "FAIL"
    assert "user.email" in checks["repo app"].detail
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
    from agent_build_kit.cli import doctor

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
    from agent_build_kit.cli import doctor

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
    checks = by_name(
        run_doctor(workspace / "abk.yaml", run=Answers(protection=True), which=which_all)
    )

    assert checks["merge guard app"].status == "ok"
