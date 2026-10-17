"""The shipped skills explain holds, stalled pipelines and authoring limits
(spec: skill-guidance).

Each addition is pinned by a key phrase, so a later edit cannot drop it. The
no-installation-names rule stays in tests/test_skills.py.
"""

import re

import pytest

from agent_build_kit import skills
from tests.prompt_text import flat


def text(name: str) -> str:
    return flat(skills.source(name)).lower()


def section(name: str, heading: str) -> str:
    """The squeezed, lower-cased body under `heading`, up to the next heading at its level."""
    body = skills.source(name)
    assert heading in body, f"{name} has no section {heading!r}"
    level = len(heading) - len(heading.lstrip("#"))
    after = body.split(heading, 1)[1]
    return flat(re.split(rf"^#{{1,{level}}} ", after, maxsplit=1, flags=re.MULTILINE)[0]).lower()


PIPELINE_PHRASES = {
    "approve records only": "`abk approve` only records",
    "approve changes no state": "changes no state",
    "exits of a label-less hold": "requeue, merge or close",
    "release only for the label": "release applies only to a hold the `agent-hold` label made",
    "limit: planning-repo files": "cannot edit planning-repo files",
    "limit: live or credentialed checks": "live or credentialed check",
    "limit: sensitive files": "sensitive file",
    "limit: uv lock": "`uv lock`",
    "lingering": "lingering",
    "enable-linger": "loginctl enable-linger",
    "running with no process": "marked `running` with no process",
    "never under a timeout": "never under a timeout",
    "slot rule": "count against their own project's `project_limits.max_units_in_progress`",
    "usage report by": "abk report --by",
    "usage report context": "--context",
}


@pytest.mark.parametrize("phrase", PIPELINE_PHRASES.values(), ids=PIPELINE_PHRASES.keys())
def test_pipeline_skill_says(phrase: str) -> None:
    assert phrase.lower() in text("abk-pipeline")


def test_pipeline_skill_has_a_holds_and_exits_table() -> None:
    body = skills.source("abk-pipeline")
    heading = re.search(r"^#+ .*\bholds?\b.*\bexits?\b.*$", body, re.I | re.M)

    assert heading, "no heading for the holds and their exits"
    table = section("abk-pipeline", heading.group(0))
    assert "|" in table
    for exit_name in ("requeue", "release", "merge", "close"):
        assert exit_name in table


def test_pipeline_skill_has_a_needs_a_human_section() -> None:
    body = skills.source("abk-pipeline")

    assert re.search(r"^#+ .*needs a human", body, re.I | re.M)


def test_pipeline_skill_has_a_when_nothing_is_moving_section() -> None:
    body = skills.source("abk-pipeline")

    assert re.search(r"^#+ When nothing is moving", body, re.M)


AUTHORING_PHRASES = {
    "first heading": "first heading is `# title`",
    "change heading unreadable": "`## change:` heading leaves the group unreadable",
    "acceptance none form": "`acceptance: none — reason`",
    "no task a builder cannot do": "do not write a task a builder cannot do",
    "live numbers": "live numbers",
    "the change's own files": "the change's own files",
    "first tier 2 run": "first tier 2 run",
    "fix round": "fix round",
    "confirm the premise": "confirm a measurement's premise",
    "same-repo needs": "same-repo `needs:`",
    "cross-repo needs": "cross-repo `needs:`",
    "hold a change behind a merge": "hold the change",
    "tags takes a change name": "`abk tags` takes a change name",
}


@pytest.mark.parametrize("phrase", AUTHORING_PHRASES.values(), ids=AUTHORING_PHRASES.keys())
def test_authoring_skill_says(phrase: str) -> None:
    assert phrase.lower() in text("abk-authoring")


CONFIG_PHRASES = {
    "sh -c form": "sh -c",
    "subshell directory change": "(cd ",
    "npm ci --prefix is not accepted": "`npm ci --prefix` is not accepted",
}


@pytest.mark.parametrize("phrase", CONFIG_PHRASES.values(), ids=CONFIG_PHRASES.keys())
def test_config_skill_says(phrase: str) -> None:
    assert phrase.lower() in text("abk-config")
