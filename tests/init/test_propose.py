"""The propose step: a model writes a change, and it has to pass the same
checks a hand-written one does — or get one repair round, then stop."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.init.detect import RepoDetection
from agent_build_kit.init.propose import ALLOWED_TOOLS, ProposeError, build_prompt, propose
from tests.factories import init_repo

GOOD_TASKS = """\
## 1. [app] [tier1] Test layout and markers

- [ ] 1.1 Add tests/conftest.py with the markers
- [ ] 1.2 Exclude marked tiers by default

## 2. [app] [tier2] [acceptance] Run the suite as a consumer would

- [ ] 2.1 Run pytest from a clean checkout
"""

BAD_TASKS = """\
## 1. [elsewhere] [tier1] Wrong repo tag

- [ ] 1.1 A task
"""


def write_change(planning: Path, change: str, tasks: str = GOOD_TASKS) -> None:
    root = planning / "openspec" / "changes" / change
    (root / "specs" / "test-harness").mkdir(parents=True, exist_ok=True)
    (root / "proposal.md").write_text("## Why\n\nNo tests.\n\n## What Changes\n\n- Add them.\n")
    (root / "design.md").write_text("## Context\n\nuv project.\n\n## Decisions\n\n- pytest.\n")
    (root / "specs" / "test-harness" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: Tiers\nThe suite SHALL exclude marked tests.\n\n"
        "#### Scenario: default run (unit)\n- **GIVEN** a marked test\n- **WHEN** pytest runs\n"
        "- **THEN** it is deselected\n"
    )
    (root / "tasks.md").write_text(tasks)


def detection(path: Path, **overrides) -> RepoDetection:
    fields = {
        "path": path,
        "name": path.name,
        "is_git": True,
        "slug": "example/app",
        "default_branch": "main",
        "languages": ["python"],
        "profile": "python-uv",
        "has_code": True,
        "service_dirs": ["api"],
        "dev_stack_script": None,
        "credentials_array": None,
        "dependency_refs": [],
        "consumes": [],
    }
    return RepoDetection.model_validate({**fields, **overrides})


def valid_report(planning: Path):
    """An OpenSpec validate stand-in that reports every change directory valid."""

    def run(argv, *, cwd, **kwargs):
        args = argv[len(openspec.command()) :]
        assert args[0] == "validate"
        changes = sorted(p.name for p in (cwd / "openspec" / "changes").iterdir() if p.is_dir())
        items = [{"id": name, "type": "change", "valid": True, "issues": []} for name in changes]
        return subprocess.CompletedProcess(argv, 0, json.dumps({"items": items}), "")

    return run


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    root = init_repo(tmp_path / "planning")
    (root / "openspec" / "changes").mkdir(parents=True)
    (root / "docs" / "recommendations").mkdir(parents=True)
    (root / "docs" / "recommendations" / "python.md").write_text("## Linting\n\n- ruff\n")
    return root


@pytest.fixture
def app(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "app")
    (repo / "pyproject.toml").write_text('[project]\nname = "app"\n' + "x = 1\n" * 80)
    (repo / "api").mkdir()
    (repo / "api" / "Dockerfile").write_text("FROM scratch\n")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")
    return repo


def test_the_prompt_carries_the_repo_the_rules_and_the_recommendations(app: Path) -> None:
    prompt = build_prompt(
        "app",
        detection(app),
        change="app-testing-infrastructure",
        kind="testing-infrastructure",
        recommendations="## Linting\n\n- ruff\n",
        repos=("platform", "app"),
    )

    assert "openspec/changes/app-testing-infrastructure/" in prompt
    assert "tests-first gate" in prompt
    assert "## <n>. [<repo>] [<tier>] <title>" in prompt
    assert "platform, app" in prompt
    assert "[platform], [app]" in prompt, "the rules block names the real repos"
    assert "Test tasks come before implementation" in prompt
    assert "Acceptance: none" in prompt
    assert "pyproject.toml (first 60 lines)" in prompt
    assert "… (22 more lines)" in prompt, "tooling files are truncated"
    assert ".github/workflows/ci.yml" in prompt
    assert "api/" in prompt
    assert "- ruff" in prompt


def test_the_prompt_carries_the_tooling_of_each_nested_project(tmp_path: Path) -> None:
    """A repo whose projects sit below the root: the model was handed a top-level
    listing and nothing else, because the tooling files it reads were looked for
    at the root only. Each detected project brings its own, named by path."""
    repo = init_repo(tmp_path / "accelerators")
    poc = repo / "pipelines" / "poc"
    poc.mkdir(parents=True)
    (poc / "pyproject.toml").write_text('[project]\nname = "poc"\n')
    web = poc / "web"
    web.mkdir()
    (web / "package.json").write_text('{"name": "web"}\n')

    prompt = build_prompt(
        "accelerators",
        detection(
            repo,
            languages=["python", "javascript"],
            projects=[
                {"path": "pipelines/poc", "languages": ["python"]},
                {"path": "pipelines/poc/web", "languages": ["javascript"]},
            ],
        ),
        change="accelerators-code-standards",
        kind="code-standards",
        recommendations="## Linting\n\n- ruff\n",
        repos=("accelerators",),
    )

    assert "pipelines/poc/pyproject.toml (first 60 lines)" in prompt
    assert 'name = "poc"' in prompt
    assert "pipelines/poc/web/package.json (first 60 lines)" in prompt
    assert '"name": "web"' in prompt
    assert "Projects: pipelines/poc, pipelines/poc/web" in prompt


def test_the_code_standards_brief() -> None:
    prompt = build_prompt(
        "app",
        detection(Path("/nonexistent")) if False else detection(Path.cwd()),
        change="app-code-standards",
        kind="code-standards",
        recommendations="",
        repos=("app",),
    )
    assert "types, formatting, linting" in prompt
    assert "(no recommendations document yet)" in prompt


def test_a_valid_change_is_written_by_one_fenced_call(planning: Path, app: Path) -> None:
    calls: list[tuple[list[str], Path]] = []

    def claude(argv, *, cwd):
        calls.append((argv, cwd))
        write_change(cwd, "app-testing-infrastructure")
        return "done"

    change = propose(
        "app",
        detection(app),
        planning=planning,
        recommendations=planning / "docs" / "recommendations" / "python.md",
        kind="testing-infrastructure",
        run_claude=claude,
        run_openspec=valid_report(planning),
        repos=("platform", "app"),
    )

    assert change == "app-testing-infrastructure"
    [(argv, cwd)] = calls
    assert cwd == planning
    assert argv[argv.index("--add-dir") + 1] == str(app)
    assert argv[argv.index("--allowedTools") + 1] == ALLOWED_TOOLS
    settings = json.loads(argv[argv.index("--settings") + 1])
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "agent_build_kit.hooks.policy" in command
    assert "--specs" not in command, "the agent writes into openspec/, so it is not read-only"
    assert "--branch-prefix" in command


def test_tag_errors_get_one_repair_round(planning: Path, app: Path) -> None:
    prompts: list[str] = []

    def claude(argv, *, cwd):
        prompts.append(argv[2])
        write_change(cwd, "app-code-standards", BAD_TASKS if len(prompts) == 1 else GOOD_TASKS)
        return ""

    propose(
        "app",
        detection(app),
        planning=planning,
        recommendations=planning / "missing.md",
        kind="code-standards",
        run_claude=claude,
        run_openspec=valid_report(planning),
        repos=("app",),
    )

    assert len(prompts) == 2
    assert "validation failed" in prompts[1]
    assert 'unknown repo "elsewhere"' in prompts[1]
    assert prompts[1].startswith(prompts[0]), "the repair prompt is the original plus the errors"


def test_a_second_failure_raises_and_leaves_the_files(planning: Path, app: Path) -> None:
    def claude(argv, *, cwd):
        write_change(cwd, "app-code-standards", BAD_TASKS)
        return ""

    with pytest.raises(ProposeError, match="left in openspec/changes/app-code-standards/"):
        propose(
            "app",
            detection(app),
            planning=planning,
            recommendations=planning / "missing.md",
            kind="code-standards",
            run_claude=claude,
            run_openspec=valid_report(planning),
            repos=("app",),
        )

    assert (planning / "openspec" / "changes" / "app-code-standards" / "tasks.md").exists()


def test_openspec_issues_are_reported_by_message(planning: Path, app: Path) -> None:
    def claude(argv, *, cwd):
        write_change(cwd, "app-code-standards")
        return ""

    def invalid(argv, *, cwd, **kwargs):
        report = {
            "items": [
                {
                    "id": "app-code-standards",
                    "type": "change",
                    "valid": False,
                    "issues": [{"level": "ERROR", "message": "proposal.md missing ## Why"}],
                }
            ]
        }
        return subprocess.CompletedProcess(argv, 1, json.dumps(report), "")

    with pytest.raises(ProposeError, match="proposal.md missing ## Why"):
        propose(
            "app",
            detection(app),
            planning=planning,
            recommendations=planning / "missing.md",
            kind="code-standards",
            run_claude=claude,
            run_openspec=invalid,
            repos=("app",),
        )


def test_a_change_the_model_never_wrote_is_an_error(planning: Path, app: Path) -> None:
    with pytest.raises(ProposeError, match="tasks.md is missing"):
        propose(
            "app",
            detection(app),
            planning=planning,
            recommendations=planning / "missing.md",
            kind="code-standards",
            run_claude=lambda argv, *, cwd: "",
            run_openspec=lambda argv, **kw: subprocess.CompletedProcess(
                argv, 0, '{"items": []}', ""
            ),
            repos=("app",),
        )
