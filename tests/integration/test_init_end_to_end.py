"""`abk init` with the real OpenSpec CLI: init, validate, and a canned change.

The model is a stub that writes one valid change per proposal; everything
else — `openspec init`, `openspec validate --strict`, the tag check, the
commit — is real. Needs node (npx) and, on the first run, the network.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.config import load
from tests.factories import coded_repo, git, recognised_planning
from tests.openspec_cli import require

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.usefixtures("openspec_cli"),
]


def write_change(planning: Path, change: str, repo: str) -> None:
    root = planning / "openspec" / "changes" / change
    (root / "specs" / "test-harness").mkdir(parents=True, exist_ok=True)
    (root / "proposal.md").write_text(
        f"## Why\n\nThe {repo} repo has no test gate.\n\n## What Changes\n\n"
        f"- Add a pytest layout. Repos touched: {repo}.\n\n## Impact\n\n- {repo}: new tests/.\n"
    )
    (root / "design.md").write_text("## Context\n\nA uv project.\n\n## Decisions\n\n- pytest.\n")
    (root / "specs" / "test-harness" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: Test tiers\n"
        "The repo SHALL run unmarked tests by default.\n\n"
        "#### Scenario: default run excludes integration tests (unit)\n"
        "- **GIVEN** a test marked integration\n- **WHEN** pytest runs\n"
        "- **THEN** it is deselected\n"
    )
    (root / "tasks.md").write_text(
        f"## 1. [{repo}] [unit-test] Test layout and markers\n\n"
        "- [ ] 1.1 Add tests/conftest.py and markers\n- [ ] 1.2 Exclude marked tiers by default\n\n"
        f"## 2. [{repo}] [e2e-test] [acceptance] Run the suite as a consumer would\n\n"
        "- [ ] 2.1 Run pytest from a clean checkout\n"
    )


def stub_claude(argv, *, cwd=None):
    prompt = argv[2]
    if "openspec/changes/" not in prompt:
        return "## Formatting\n\n- one formatter\n\n## Sources\n\n- https://example.invalid\n"
    change = prompt.split("openspec/changes/", 1)[1].split("/", 1)[0]
    repo = change.rsplit("-code-standards", 1)[0].rsplit("-testing-infrastructure", 1)[0]
    assert cwd is not None
    write_change(cwd, change, repo)
    return ""


def test_init_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_cmd, "run_claude", stub_claude)
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "t")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "t@t.t")
    app = coded_repo(tmp_path / "app", "example/app")
    planning = recognised_planning(tmp_path / "planning")

    # The runtime is named and `claude` pretended to be on the path, so the run does not
    # depend on which agents this machine has.
    monkeypatch.setattr(init_cmd, "which", lambda program: f"/fake/{program}")
    # `abk init` runs `openspec init`; a missing CLI is reported as that, not as init failing.
    require(openspec.run(["init", "--help"], cwd=planning))
    code = main(
        [
            *("init", str(planning), "--repo", str(app), "--yes"),
            *("--runtime", "claude_code", "--agent-command", "claude"),
        ]
    )

    assert code == 0
    assert load(planning / "abk.yaml").repos["app"].slug == "example/app"
    assert (planning / ".claude" / "skills" / "openspec-propose" / "SKILL.md").exists(), (
        "openspec init set Claude Code up"
    )
    for change in ("app-testing-infrastructure", "app-code-standards"):
        assert (planning / "openspec" / "changes" / change / "tasks.md").exists()
    result = require(openspec.validate(planning))
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"failed": 0' in result.stdout
    assert "abk init: workspace app" in git(planning, "log", "--oneline")
    assert git(planning, "status", "--porcelain") == ""
    assert main(["--config", str(planning / "abk.yaml"), "tags", "--all"]) == 0
