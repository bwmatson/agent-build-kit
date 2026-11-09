"""What a build agent is told the gate runs for a node project follows the project's own
`lint`, `format:check` and `typecheck` scripts (spec: node-npm-lint-and-test).

The sentence a rework gets about the checks CI ran and the commands the agent may run both
read the commands the gate would run for that project.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.config import AgentPurpose, RepoConfig
from agent_build_kit.pipeline import agent_commands, events
from tests.forges.stand_in import StandInForge, lookup
from tests.pipeline.test_events import checks_pull

LINT = {"lint": "oxlint src"}
FORMAT = {"format:check": "oxfmt --check src"}
TYPES = {"typecheck": "tsc -p tsconfig.app.json --noEmit"}

# Each kind of project: its `scripts`, and the lint, format and type-check commands it gets.
GENERIC = ("npx oxlint .", "npx oxfmt --check .", "npx tsc --noEmit")
KINDS: dict[str, tuple[dict[str, str] | None, tuple[str, str, str]]] = {
    "all three scripts": (
        {**LINT, **FORMAT, **TYPES},
        ("npm run lint", "npm run format:check", "npm run typecheck"),
    ),
    "lint and format:check": (
        {**LINT, **FORMAT},
        ("npm run lint", "npm run format:check", "npx tsc --noEmit"),
    ),
    "only lint": (LINT, ("npm run lint", "npx oxfmt --check .", "npx tsc --noEmit")),
    "neither script": ({"build": "tsc"}, GENERIC),
    "no scripts field": (None, GENERIC),
}


def node_repo(where: Path, scripts: dict[str, str] | None) -> RepoConfig:
    """A node-npm repo at `where` whose `package.json` has `scripts` (no field when None)."""
    where.mkdir()
    manifest: dict[str, object] = {"name": "app", "version": "1.0.0"}
    if scripts is not None:
        manifest["scripts"] = scripts
    (where / "package.json").write_text(json.dumps(manifest))
    return RepoConfig(path=where, slug="example/app", profile="node-npm")


def note_for(repo: RepoConfig) -> str:
    """The reproduction note a rework gets for a failing check in `repo`, activated as `app`."""
    current = config_module.active()
    config_module.activate(
        current.model_copy(update={"repos": {"app": repo}}), config_module.active_root()
    )
    fetch = events.build_fetch_check_logs(for_repo=lookup(StandInForge()))
    return fetch("app", checks_pull("lint"))


def agent_lines(repo: RepoConfig) -> dict[str, str]:
    """The command line a build agent may run for each of lint, format and type check."""
    wanted = {AgentPurpose.LINT, AgentPurpose.FORMAT, AgentPurpose.CHECK}
    return {
        item.purpose: " ".join(item.command)
        for item in agent_commands.effective(repo)
        if item.purpose in wanted
    }


def other_spelling(command: str) -> str:
    """The spelling of the same check that the gate does not run for this project."""
    return {
        "npm run lint": "npx oxlint",
        "npx oxlint .": "npm run lint",
        "npm run format:check": "npx oxfmt",
        "npx oxfmt --check .": "npm run format:check",
    }[command]


@pytest.mark.parametrize("kind", KINDS)
def test_the_note_names_only_the_lint_and_format_commands_the_gate_runs_for_the_project(
    kind: str, tmp_path: Path
) -> None:
    scripts, (lint, format_check, _) = KINDS[kind]

    note = note_for(node_repo(tmp_path / "project", scripts))

    assert lint in note
    assert format_check in note
    assert other_spelling(lint) not in note
    assert other_spelling(format_check) not in note


@pytest.mark.parametrize("kind", ["all three scripts", "lint and format:check", "only lint"])
def test_the_commands_an_agent_may_run_are_the_ones_the_gate_runs_for_the_project(
    kind: str, tmp_path: Path
) -> None:
    scripts, (lint, format_check, types) = KINDS[kind]

    lines = agent_lines(node_repo(tmp_path / "project", scripts))

    assert lines == {
        AgentPurpose.LINT: lint,
        AgentPurpose.FORMAT: format_check,
        AgentPurpose.CHECK: types,
    }
