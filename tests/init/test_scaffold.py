"""Drafting abk.yaml and laying out the planning repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from agent_build_kit import openspec
from agent_build_kit.config import load
from agent_build_kit.forges import RepoId
from agent_build_kit.init.detect import ProjectDetection, RepoDetection
from agent_build_kit.init.scaffold import (
    RULES_HEADER,
    ScaffoldError,
    draft_config,
    is_unconfigured_openspec_config,
    render_context,
    render_openspec_config,
    render_rules,
    render_systemd,
    rules_of,
    write_planning_repo,
)

STOCK_CONFIG = (
    "schema: spec-driven\n\n# context: |\n#   ...\n# rules:\n#   proposal:\n#     - ...\n"
)


def detection(name: str, root: Path, **overrides) -> RepoDetection:
    fields = {
        "path": root / name,
        "name": name,
        "is_git": True,
        "slug": f"example/{name}",
        "default_branch": "main",
        "languages": ["python"],
        "profile": "python-uv",
        "has_code": True,
        "service_dirs": [],
        "dev_stack_script": None,
        "credentials_array": None,
        "dependency_refs": [],
        "consumes": [],
    }
    return RepoDetection.model_validate({**fields, **overrides})


def fake_openspec(argv, *, cwd, **kwargs):
    """A stand-in for the OpenSpec CLI: `init` writes the stock layout."""
    args = argv[len(openspec.command()) :]
    if args[0] == "init":
        (cwd / "openspec" / "changes" / "archive").mkdir(parents=True)
        (cwd / "openspec" / "specs").mkdir()
        (cwd / "openspec" / "config.yaml").write_text(STOCK_CONFIG)
        return subprocess.CompletedProcess(argv, 0, "ok", "")
    return subprocess.CompletedProcess(argv, 0, "", "")


# --- draft_config ------------------------------------------------------------------


def test_draft_orders_consumed_repos_first_and_skeletons_deploy_rules(tmp_path: Path) -> None:
    detections = {
        "app": detection("app", tmp_path, consumes=["platform"], service_dirs=["api", "worker"]),
        "platform": detection("platform", tmp_path),
    }

    config = draft_config(detections, planning_dir=tmp_path / "planning")

    assert list(config.repos) == ["platform", "app"]
    app = config.repos["app"]
    assert [rule.prefix for rule in app.deploy.rules] == ["api/", "worker/"]
    assert all(rule.run == [] for rule in app.deploy.rules)
    assert app.consumes == ["platform"]
    assert app.slug == "example/app"
    assert app.languages == ["python"]


def test_draft_uses_dev_stack_and_credentials_when_detected(tmp_path: Path) -> None:
    detections = {
        "app": detection(
            "app",
            tmp_path,
            dev_stack_script="scripts/dev-stack.sh",
            credentials_array="TEST_CREDENTIALS",
        )
    }

    app = draft_config(detections, planning_dir=tmp_path).repos["app"]

    assert app.dev_stack is not None and app.dev_stack.script == "scripts/dev-stack.sh"
    assert app.deploy.credentials is not None
    assert app.deploy.credentials.names_from is not None
    assert app.deploy.credentials.names_from.shell_array == "TEST_CREDENTIALS"


def test_consumes_override_replaces_the_detected_list(tmp_path: Path) -> None:
    detections = {
        "app": detection("app", tmp_path, consumes=["platform"]),
        "platform": detection("platform", tmp_path),
    }

    config = draft_config(
        detections, planning_dir=tmp_path, consumes_overrides={"app": [], "platform": ["app"]}
    )

    assert config.repos["app"].consumes == []
    assert config.repos["platform"].consumes == ["app"]
    assert list(config.repos) == ["app", "platform"]


def test_consumes_naming_an_unknown_repo_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ScaffoldError, match="not a repo here"):
        draft_config(
            {"app": detection("app", tmp_path)},
            planning_dir=tmp_path,
            consumes_overrides={"app": ["elsewhere"]},
        )


def test_a_repo_without_an_origin_gets_a_placeholder_slug(tmp_path: Path) -> None:
    config = draft_config({"app": detection("app", tmp_path, slug=None)}, planning_dir=tmp_path)

    assert config.repos["app"].slug == "todo-owner/app"


# --- rendering --------------------------------------------------------------------------


def test_rules_render_the_workspace_repos_and_parse_as_yaml() -> None:
    text = render_rules(["app", "platform"])

    assert text.startswith(RULES_HEADER)
    loaded = yaml.safe_load(text)
    assert set(loaded) == {"rules", "operations"}
    assert set(loaded["rules"]) == {"proposal", "specs", "design", "tasks"}
    tasks = "\n".join(loaded["rules"]["tasks"])
    assert "[app], [platform]" in tasks
    assert "## 1. [app] [tier1]" in tasks
    assert "abk tags" in tasks
    assert loaded["operations"]["apply"]["guidance"]


def test_openspec_config_carries_context_and_rules(tmp_path: Path) -> None:
    config = draft_config(
        {
            "app": detection("app", tmp_path, consumes=["platform"]),
            "platform": detection("platform", tmp_path),
        },
        planning_dir=tmp_path,
    )

    text = render_openspec_config(config)
    loaded = yaml.safe_load(text)

    assert loaded["schema"] == "spec-driven"
    assert "**app**" in loaded["context"]
    assert "app consumes platform" in loaded["context"]
    assert "tests/integration/" in loaded["context"]
    assert rules_of(text) == rules_of(render_rules(["platform", "app"]))


def test_context_mentions_each_repo_once_with_its_facts(tmp_path: Path) -> None:
    config = draft_config({"app": detection("app", tmp_path)}, planning_dir=tmp_path)

    context = render_context(config)

    assert context.count("**app**") == 1
    assert "example/app" in context
    assert "languages: python" in context


def test_the_draft_lists_each_project_in_the_repo(tmp_path: Path) -> None:
    """A repo can hold more than one project - a Python service with a web app
    under it - and abk.yaml is where a person sees which, and what each is
    written in. The repo-level profile alone said "python-uv" and nothing about
    where either project lives."""
    detected = detection(
        "accelerators",
        tmp_path,
        languages=["python", "javascript", "typescript"],
        projects=[
            ProjectDetection(path="pipelines/poc", languages=["python"], profile="python-uv"),
            ProjectDetection(
                path="pipelines/poc/web", languages=["javascript", "typescript"], profile="node-npm"
            ),
        ],
    )

    config = draft_config({"accelerators": detected}, planning_dir=tmp_path / "planning")

    assert [(p.path, p.languages, p.profile) for p in config.repos["accelerators"].projects] == [
        ("pipelines/poc", ["python"], "python-uv"),
        ("pipelines/poc/web", ["javascript", "typescript"], "node-npm"),
    ]


def test_systemd_units_render_the_planning_path(tmp_path: Path) -> None:
    units = render_systemd(tmp_path / "planning")

    assert set(units) == {
        "abk-tick.service",
        "abk-tick.timer",
        "abk-track-health.service",
        "abk-track-health.timer",
        "abk-track-improve.service",
        "abk-track-improve.timer",
        "abk-track-recommend.service",
        "abk-track-recommend.timer",
    }
    tick = units["abk-tick.service"]
    assert f"WorkingDirectory={tmp_path / 'planning'}" in tick
    assert "ExecStart=/usr/bin/env uv run abk tick" in tick
    assert 'Environment="VOLTA_HOME=%h/.volta"' in tick
    assert "ExecStart=/usr/bin/env uv run abk track health" in units["abk-track-health.service"]
    assert "OnUnitActiveSec=5min" in units["abk-tick.timer"]
    assert "OnCalendar=*-*-* 06:47:00" in units["abk-track-health.timer"]
    assert "Persistent=true" in units["abk-track-health.timer"]
    assert "OnCalendar=Sun *-*-* 09:00:00" in units["abk-track-improve.timer"]
    assert "OnCalendar=Wed *-*-* 07:23:00" in units["abk-track-recommend.timer"]


def test_stock_openspec_config_is_recognised(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(STOCK_CONFIG)
    assert is_unconfigured_openspec_config(path)

    path.write_text("schema: spec-driven\nrules:\n  tasks:\n    - mine\n")
    assert not is_unconfigured_openspec_config(path)


# --- write_planning_repo -----------------------------------------------------------------


def test_the_planning_repo_is_laid_out(tmp_path: Path) -> None:
    planning = tmp_path / "planning"
    config = draft_config({"app": detection("app", tmp_path)}, planning_dir=planning)

    written = write_planning_repo(planning, config, run_openspec=fake_openspec)

    assert (planning / ".git").is_dir()
    assert load(planning / "abk.yaml").repos["app"].slug == "example/app"
    assert (planning / "runs" / ".gitkeep").exists()
    assert (planning / "runs" / "units.json").read_text() == '{"units": []}\n'
    assert ".env" in (planning / ".gitignore").read_text()
    assert "runs/unit-logs/" in (planning / ".gitignore").read_text()
    assert "GH_TOKEN" in (planning / ".env.example").read_text()
    assert "abk-pipeline" in (planning / "CLAUDE.md").read_text()
    assert not (planning / "systemd").exists(), (
        "units are rendered by `abk install-timers` on the machine that runs "
        "them; one written here names whoever ran init"
    )
    for name in ("abk-pipeline", "abk-authoring", "abk-config"):
        assert (planning / ".claude" / "skills" / name / "SKILL.md").exists()
    openspec_config = (planning / "openspec" / "config.yaml").read_text()
    assert RULES_HEADER in openspec_config
    assert "[app]" in openspec_config
    assert planning / "abk.yaml" in written


def test_a_second_run_writes_nothing_and_keeps_edits(tmp_path: Path) -> None:
    planning = tmp_path / "planning"
    config = draft_config({"app": detection("app", tmp_path)}, planning_dir=planning)
    write_planning_repo(planning, config, run_openspec=fake_openspec)
    (planning / "abk.yaml").write_text("version: 1\nrepos: {}\n")
    (planning / "openspec" / "config.yaml").write_text(
        "schema: spec-driven\nrules:\n  tasks: [x]\n"
    )
    (planning / "CLAUDE.md").write_text("mine\n")

    def refuse(argv, **kwargs):
        raise AssertionError("openspec must not run again once openspec/ exists")

    written = write_planning_repo(planning, config, run_openspec=refuse)

    skills = [path for path in written if ".claude" in path.parts]
    assert written == skills, "only the framework's own skills are rewritten"
    assert (planning / "abk.yaml").read_text() == "version: 1\nrepos: {}\n"
    assert "tasks: [x]" in (planning / "openspec" / "config.yaml").read_text()
    assert (planning / "CLAUDE.md").read_text() == "mine\n"


def test_force_rewrites_the_two_edited_files(tmp_path: Path) -> None:
    planning = tmp_path / "planning"
    config = draft_config({"app": detection("app", tmp_path)}, planning_dir=planning)
    write_planning_repo(planning, config, run_openspec=fake_openspec)
    (planning / "abk.yaml").write_text("version: 1\nrepos: {}\n")
    (planning / "openspec" / "config.yaml").write_text("schema: spec-driven\n")

    write_planning_repo(planning, config, run_openspec=fake_openspec, force=True)

    assert load(planning / "abk.yaml").repos
    assert RULES_HEADER in (planning / "openspec" / "config.yaml").read_text()


def test_a_failed_openspec_init_is_an_error(tmp_path: Path) -> None:
    def failing(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "npx: not found")

    with pytest.raises(ScaffoldError, match="openspec init failed"):
        write_planning_repo(
            tmp_path / "planning", draft_config({}, planning_dir=tmp_path), run_openspec=failing
        )


def test_an_azure_repo_is_written_with_its_own_block(tmp_path: Path) -> None:
    """Each forge names a repo its own way, and writes the keys it says it
    requires — so the file it drafts is one that loads."""
    found = detection(
        "accelerators",
        tmp_path,
        slug=None,
        identity=RepoId(
            forge="azure_devops", account="acme", project="Some Project", name="Some Repo"
        ),
    )

    config = draft_config({"accelerators": found}, planning_dir=tmp_path)

    entry = config.repos["accelerators"]
    assert entry.forge == "azure_devops"
    assert (entry.azure_devops.org, entry.azure_devops.project) == ("acme", "Some Project")
    assert entry.azure_devops.repo == "Some Repo"
    assert entry.slug == "", "no placeholder owner for a host that has no owner/name"


def test_a_github_repo_is_still_written_with_its_slug(tmp_path: Path) -> None:
    config = draft_config({"app": detection("app", tmp_path)}, planning_dir=tmp_path)

    assert config.repos["app"].forge == "github"
    assert config.repos["app"].slug == "example/app"
