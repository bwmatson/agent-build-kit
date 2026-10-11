"""The review prompt looks for prior art and blocks on a duplicate the change introduces."""

from agent_build_kit.pipeline.wiring import REVIEW_PROMPT


def _rule(marker: str) -> str:
    """The squeezed, lower-cased bullet of the review prompt that holds `marker`."""
    bullets = [" ".join(b.split()).lower() for b in REVIEW_PROMPT.split("\n- **")]
    held = [b for b in bullets if marker in b]
    assert held, f"no rule of the review prompt mentions {marker!r}"
    return held[0]


# 2.1 — the search step


def test_each_new_definition_is_searched_for_an_existing_equivalent() -> None:
    step = _rule("existing equivalent")

    for kind in ("function", "constant", "pattern", "test helper"):
        assert kind in step
    assert "diff" in step
    assert "second copy" in step


def test_the_existing_equivalent_is_named_by_file_and_line() -> None:
    assert "file and line" in _rule("existing equivalent")


# 2.2 — the rule


def test_a_duplicate_the_change_introduces_is_a_required_finding() -> None:
    rule = _rule("makes worse")

    assert "introduces or makes worse" in rule
    assert "required" in rule
    assert "change together" in rule


def test_the_rule_says_what_done_looks_like() -> None:
    rule = _rule("makes worse")

    assert "done" in rule
    assert "existing" in rule
    assert "shared function" in rule


def test_the_common_cases_are_named() -> None:
    rule = _rule("makes worse")

    assert "parallel" in rule and "call site" in rule
    assert "per-variant" in rule or "each variant" in rule


def test_the_rule_satisfies_the_required_finding_consequence_rule() -> None:
    rule = _rule("makes worse")

    assert "consequence" in rule
    assert "finding whose consequence you cannot name" in " ".join(REVIEW_PROMPT.split())


# 2.3 — what it does not ask for


def test_duplication_the_change_leaves_alone_is_not_to_be_reported() -> None:
    rule = _rule("makes worse")

    assert "neither adds to nor extends" in rule
    assert "follow-up" not in rule
    assert "optional" not in rule.split("neither adds to nor extends")[0].split("makes worse")[-1]


def test_the_split_between_local_and_design_level_refactors_stays() -> None:
    shallow = _rule("shallow interfaces")

    assert "small and local" in shallow
    assert "design decision" in shallow
    assert "optional" in shallow


def test_the_rule_follows_the_interfaces_rule() -> None:
    prompt = " ".join(REVIEW_PROMPT.split()).lower()

    assert prompt.index("shallow interfaces") < prompt.index("makes worse")
    assert prompt.index("makes worse") < prompt.index("read the code around the change")
