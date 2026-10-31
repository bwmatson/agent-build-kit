"""The `abk-authoring` skill has a section on how to word the tasks of an `[e2e-test]` group, with a
bad and a good example and a checklist line, and names the same two routes for a product fault as
the warning `abk tags` gives (spec: e2e-task-wording)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from agent_build_kit import skills
from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import OPT_OUT, Replan
from tests.prompt_text import flat

HEADING = "Word the tasks of an `[e2e-test]` group"
BAD_EXAMPLE = "Fix whatever the subprocess run shows that in-process calls could not"
ROUTES = ("product-defect", "[unit-test]", "Needs:")


@pytest.fixture
def raw_texts(tmp_path: Path) -> list[str]:
    """The source skill and the mirror the installer writes."""
    skills.install(tmp_path / ".claude" / "skills")
    mirror = tmp_path / ".claude" / "skills" / "abk-authoring" / "SKILL.md"
    return [skills.source("abk-authoring"), mirror.read_text(encoding="utf-8")]


def section(text: str) -> str:
    """The text under the heading, up to the next heading of the same or a higher level."""
    match = re.search(rf"^(#+) {re.escape(HEADING)}\n(.*?)(?=^#{{1,2}} |\Z)", text, re.M | re.S)
    assert match, HEADING
    return flat(match.group(2))


def test_the_skill_has_the_section_after_what_an_e2e_group_holds(raw_texts: list[str]) -> None:
    for text in raw_texts:
        assert text.index("What an `[e2e-test]` group holds") < text.index(HEADING)


def test_the_section_shows_a_bad_and_a_good_wording(raw_texts: list[str]) -> None:
    for text in raw_texts:
        body = section(text)
        assert BAD_EXAMPLE in body
        assert re.search(r"\bbad\b", body, re.I)
        assert re.search(r"\bgood\b", body, re.I)
        assert "without changing product code" in body


def test_the_section_says_a_task_that_asks_for_a_fix_belongs_in_another_group(
    raw_texts: list[str],
) -> None:
    for text in raw_texts:
        body = section(text)
        assert re.search(r"could change a product file", body)
        assert re.search(r"another group", body)


def test_the_section_names_the_two_routes_for_a_product_fault(raw_texts: list[str]) -> None:
    for text in raw_texts:
        body = section(text)
        for route in ROUTES:
            assert route in body


def test_the_warning_names_the_same_two_routes_as_the_skill(
    raw_texts: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write(
        "live",
        f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [e2e-test] Group 1\n\n"
        f"- [ ] 1.1 Test: the run.\n- [ ] 1.2 {BAD_EXAMPLE}.\n",
    )
    capsys.readouterr()
    cli.cmd_tags(argparse.Namespace(change="live", all=False), run.inst)
    out = capsys.readouterr().out

    warnings = [line for line in out.splitlines() if "warning" in line and "group 1" in line]
    assert warnings, out
    for route in ROUTES:
        assert route in warnings[0]
        assert route in section(raw_texts[0])
