"""The "Start here" section is never shrunk at any host limit, and nothing pushes it out."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import forges
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.unit_store import Description
from agent_build_kit.pipeline.verdict import GateResult, VerdictFacts
from tests.factories import brief_description, output_of, snapshot, tier_verdict
from tests.factories import stored_unit as unit
from tests.pipeline.test_pr_body_why import write_change

START = "## Start here"
CAP = 5


def entries(prefix: str, count: int) -> list[tuple[str, str]]:
    return [(f"src/{prefix}_{n}.py", f"{prefix} reason {n} " + "r" * 80) for n in range(count)]


def start_of(body: str) -> str:
    """The section: from its heading to the next heading."""
    rest = body[body.index(START) + len(START) :]
    end = rest.find("\n## ")
    return START + (rest if end == -1 else rest[:end])


def body_of(tmp_path: Path, described: Description, *, limit: int, **kw) -> str:
    write_change(tmp_path, why="Why. " * 400)
    u = unit(tier="e2e-test", description=described)
    facts = VerdictFacts(
        kind=TestTier.E2E_TEST, red_first=GateResult.PASSED, unit_test=GateResult.PASSED
    )
    return build_pr_body(
        u,
        graph=[u],
        base="main",
        e2e_snapshot=snapshot(output_of(20_000)),
        changes_dir=tmp_path,
        limit=limit,
        facts=facts,
        rounds=2,
        verdict=tier_verdict(),
        **kw,
    )


def test_the_section_is_whole_at_the_smallest_limit_and_the_rest_shrinks(tmp_path: Path) -> None:
    limit = forges.description_limit()
    described = brief_description(entries("focus", 3), entries("skip", 3))
    described = described.model_copy(
        update={"summary": "s" * 400, "changes": tuple("c" * 300 for _ in range(6))}
    )
    roomy = body_of(tmp_path, described, limit=10 * limit, restack_note="n" * (3 * limit))

    tight = body_of(tmp_path, described, limit=limit, restack_note="n" * (3 * limit))

    assert len(tight) <= limit
    assert start_of(tight) == start_of(roomy), "the section is present whole"
    assert tight.index(START) < tight.index("## Why")
    assert len(tight) < len(roomy), "the other sections are what shrank"


def test_a_section_with_every_list_at_its_cap_leaves_room_for_the_fixed_sections(
    tmp_path: Path,
) -> None:
    limit = forges.description_limit()
    described = brief_description(entries("focus", CAP + 3), entries("skip", CAP + 3))

    body = body_of(tmp_path, described, limit=limit)

    section = start_of(body)
    assert f"focus_{CAP - 1}.py" in section
    assert f"focus_{CAP}.py" not in section, "the list is capped"
    assert f"skip_{CAP - 1}.py" in section
    assert f"skip_{CAP}.py" not in section
    assert len(body) <= limit
    for heading in ("## Why", "## Assumptions", "## e2e-test results", "## How this was built"):
        assert heading in body, "the fixed sections still fit beside the section"
