"""`abk doctor` against recorded answers from git, gh and the OpenSpec CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit import __version__, skills
from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import DeployConfig, DeployRule, RepoConfig, WorkspaceConfig, dump, load
from agent_build_kit.init.scaffold import render_openspec_config
from tests.factories import git, init_repo


class Answers:
    """A subprocess.run stand-in: gh and npx are answered here, git is real."""

    def __init__(self, *, owners: set[str] | None = None, openspec_ok: bool = True):
        self.owners = {"example"} if owners is None else owners
        self.openspec_ok = openspec_ok
        self.commands: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
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

    assert {check.status for check in checks} == {"ok"}, [c for c in checks if c.status != "ok"]
    names = by_name(checks)
    assert "repo app" in names and "gh example" in names and "openspec" in names
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


def test_a_missing_gh_account_fails(workspace: Path) -> None:
    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(owners=set()), which=which_all))

    assert checks["gh example"].status == "FAIL"
    assert "gh auth login" in checks["gh example"].fix


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


def test_rules_drift_is_a_warning_with_a_diff(workspace: Path) -> None:
    path = workspace / "openspec" / "config.yaml"
    text = path.read_text().replace(
        '    - "Number groups from 1 in the order they are built."\n', "    - my own extra rule\n"
    )
    path.write_text(text)

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["rules"].status == "warn"
    assert "1 framework rule(s)" in checks["rules"].detail
    assert "-  - Number groups from 1" in checks["rules"].detail
    assert "extra rules of your own are fine" in checks["rules"].fix


def test_extra_rules_alone_are_fine(workspace: Path) -> None:
    path = workspace / "openspec" / "config.yaml"
    numbered = '    - "Number groups from 1 in the order they are built."\n'
    path.write_text(path.read_text().replace(numbered, numbered + "    - my own extra rule\n"))

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["rules"].status == "ok"


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
