"""The pull request footer states who merges: the build agent never does, the pipeline only a unit
review classified `auto` and policy allowed."""

import re

from agent_build_kit.pipeline.pr_body import build_pr_body
from tests.factories import stored_unit as unit


def footer() -> str:
    body = build_pr_body(unit(), graph=[unit()], base="main")
    return " ".join(body.rsplit("\n---\n", 1)[-1].split())


def test_the_footer_says_the_build_agent_never_merges() -> None:
    assert "build agent never merges" in footer()


def test_the_footer_says_the_pipeline_merges_only_an_auto_unit_policy_allowed() -> None:
    text = footer()

    assert "pipeline merges" in text
    assert "auto" in text
    assert re.search(r"policy", text, re.I)


def test_the_footer_does_not_say_a_human_merges_every_one() -> None:
    assert not re.search(r"(human|person)\s+merges\s+every", footer(), re.I)
