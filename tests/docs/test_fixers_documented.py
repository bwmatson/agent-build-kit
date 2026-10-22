"""The documents, the skill and the changelog describe the fixers and the shared check loop."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
CONFIG_SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md"
CHECK_LOOP_ROWS = ("stub_checks", "fix_stub_checks", "checks", "fix_checks")


def squashed_text(text: str) -> str:
    """The text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(text.replace("`", "").split())


def squashed(path: Path) -> str:
    return squashed_text(path.read_text(encoding="utf-8"))


def node_row(name: str) -> str:
    """The unit-graph table row of one node, squashed."""
    for line in (DOCS / "unit-graph.md").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| `{name}` |"):
            return squashed_text(line)
    raise AssertionError(f"docs/unit-graph.md has no table row for {name}")


def unreleased_section() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    start = text.index("## Unreleased")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else None]


def test_the_architecture_document_says_the_fixers_run_before_each_commit() -> None:
    text = squashed(DOCS / "architecture.md")
    assert re.search(r"fixers?.{0,400}no (model|agent) call", text, re.I)
    assert re.search(r"fixers?.{0,500}tests commit", text, re.I)
    assert re.search(r"fixers?.{0,500}implementation commit", text, re.I)
    assert re.search(r"fixers?.{0,600}fix: .{0,40}checks, round", text, re.I)
    assert re.search(r"fixers?.{0,600}unit.s own files", text, re.I)


def test_the_architecture_document_says_the_two_loops_share_one_routine() -> None:
    text = squashed(DOCS / "architecture.md")
    assert re.search(r"(stub|static) (check )?loop.{0,400}one (shared )?routine", text, re.I)
    assert re.search(r"checks loop.{0,400}one (shared )?routine", text, re.I) or re.search(
        r"one (shared )?routine.{0,400}checks loop", text, re.I
    )


@pytest.mark.parametrize("name", CHECK_LOOP_ROWS)
def test_each_check_loop_row_of_the_unit_graph_names_the_shared_routine(name: str) -> None:
    assert re.search(
        r"shared (check-and-fix )?(routine|loop)|check_round|fix_round", node_row(name)
    )


@pytest.mark.parametrize("name", ("stub_checks", "fix_stub_checks", "fix_checks"))
def test_the_fixing_rows_of_the_unit_graph_say_the_fixers_run(name: str) -> None:
    assert re.search(r"fixers?", node_row(name), re.I)


@pytest.mark.parametrize("name", ("fix_stub_checks", "fix_checks"))
def test_the_fix_rows_keep_the_changed_nothing_stop(name: str) -> None:
    assert re.search(r"changed nothing", node_row(name), re.I)


def test_the_unit_graph_stub_check_edge_that_commits_names_the_fixers() -> None:
    edges = [
        line
        for line in (DOCS / "unit-graph.md").read_text(encoding="utf-8").splitlines()
        if "stub_checks -->" in line and "commits the tests" in line
    ]
    assert edges
    assert all("fixers" in edge for edge in edges)


def test_the_architecture_checks_step_names_the_fixers_before_the_fix_commit() -> None:
    text = squashed(DOCS / "architecture.md")
    step = text[text.index("Checks, then review rounds") :]
    step = step[: step.index("A read-only reviewer")]
    assert re.search(r"fixers.{0,200}no model call", step, re.I)
    assert re.search(
        r"fix: .{0,40}checks, round N.{0,200}fixers|fixers.{0,200}fix: .{0,40}checks, round", step
    )
    assert "check_loop.py" in step


def test_the_architecture_tests_and_implementation_steps_name_the_fixers() -> None:
    text = squashed(DOCS / "architecture.md")
    steps = text[text.index("Tests, commit.") : text.index("Checks, then review rounds")]
    assert re.search(r"fixers.{0,300}per_group_commits off", steps, re.I)
    assert re.search(r"runs the fixers, then commits feat:", steps)


def test_the_toolchain_profiles_document_lists_fix_command_as_optional() -> None:
    text = squashed(DOCS / "toolchain-profiles.md")
    assert re.search(r"fix_command\(files\).{0,300}optional", text, re.I)
    assert re.search(r"uv run pre-commit run --files", text)
    assert re.search(r"npx oxfmt.{0,80}npx oxlint --fix", text)
    assert re.search(r"adding .{0,40}fix_command|add .{0,40}fix_command", text, re.I)


def test_the_config_skill_names_the_setting_and_says_it_is_policy() -> None:
    text = squashed(CONFIG_SKILL)
    assert "repos.<name>.tests.fix_command" in text
    assert re.search(r"fix_command.{0,600}policy", text, re.I)
    assert re.search(r"fix_command.{0,600}abk\.yaml", text)


def test_the_changelog_holds_one_fixers_bullet_under_unreleased() -> None:
    bullets = [b for b in unreleased_section().split("\n\n") if b.lstrip().startswith("- ")]
    mine = [
        b
        for b in bullets
        if re.search(r"formatter.s edit", squashed_text(b), re.I)
        and re.search(r"fixers", squashed_text(b), re.I)
    ]
    assert len(mine) == 1
    text = squashed_text(mine[0])
    assert re.search(r"no longer stops? a stubbed build", text, re.I)
