"""A test is in at most one split: the check lists each split and `rest` through the profile
and names a test selected by two, an unknown selector and a listing that failed (spec:
tier2-splits)."""

from __future__ import annotations

import subprocess
from typing import Any

from agent_build_kit.config import Tier2Split
from agent_build_kit.pipeline.e2e_exclusive import check_splits

SPLITS = (
    Tier2Split(name="acp", marker="runtime_acp"),
    Tier2Split(name="claude_code", marker="runtime_claude_code"),
    Tier2Split(name="rest"),
)
COMMAND = ["uv", "run", "pytest", "-m", "local_stack"]
A = "tests/integration/test_live.py::test_a"
B = "tests/integration/test_live.py::test_b"
C = "tests/integration/test_live.py::test_c"
REGISTERED = ["local_stack", "runtime_acp", "runtime_claude_code"]


class FakeProfile:
    """Lists the tests given for each selection's `only`; None stands for a failed listing."""

    name = "fake"
    selector_kinds: tuple[str, ...] = ("marker",)

    def __init__(
        self, listings: dict[str, list[str] | None], registered: list[str] | None = REGISTERED
    ) -> None:
        self.listings = listings
        self.registered = registered
        self.asked: list[str | None] = []

    def expression(self, marker: str, selection: Any) -> str:
        return marker

    def list_tests(
        self, command: list[str], selection: Any, *, run: Any, among: Any = None
    ) -> list[str] | None:
        self.asked.append(selection.only)
        return self.listings[selection.only]

    def registered_selectors(self, command: list[str], *, run: Any) -> list[str] | None:
        return self.registered


def never_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    raise AssertionError(f"the fake profile runs nothing: {argv}")


def check(profile: FakeProfile, splits: Any = SPLITS) -> Any:
    return check_splits(profile, COMMAND, "local_stack", splits, run=never_run)


def counts(result: Any) -> dict[str, int | None]:
    return {
        listing.name: None if listing.tests is None else len(listing.tests)
        for listing in result.listings
    }


def test_tests_selected_by_no_two_splits_pass_and_each_split_and_rest_is_listed() -> None:
    result = check(FakeProfile({"acp": [A], "claude_code": [B], "rest": [C]}))

    assert result.findings == ()
    assert counts(result) == {"acp": 1, "claude_code": 1, "rest": 1}
    assert [listing.marker for listing in result.listings] == [
        "runtime_acp",
        "runtime_claude_code",
        None,
    ]


def test_a_test_selected_by_two_splits_is_reported_with_its_id_and_both_names() -> None:
    result = check(FakeProfile({"acp": [A, B], "claude_code": [B], "rest": [C]}))

    (finding,) = result.findings
    assert B in finding
    assert "acp" in finding
    assert "claude_code" in finding
    assert A not in finding


def test_rest_is_never_reported_against_a_split() -> None:
    result = check(FakeProfile({"acp": [A], "claude_code": [B], "rest": [A, B]}))

    assert result.findings == ()


def test_each_split_and_rest_is_listed_alone() -> None:
    profile = FakeProfile({"acp": [], "claude_code": [], "rest": []})

    check(profile)

    assert sorted(map(str, profile.asked)) == ["acp", "claude_code", "rest"]


def test_a_repo_with_no_declared_split_has_nothing_to_check() -> None:
    profile = FakeProfile({})

    result = check(profile, (Tier2Split(name="rest"),))

    assert result.findings == ()
    assert profile.asked == []


def test_a_listing_that_fails_is_reported_naming_the_split_and_is_not_an_empty_split() -> None:
    result = check(FakeProfile({"acp": [A], "claude_code": None, "rest": [C]}))

    (finding,) = result.findings
    assert "claude_code" in finding
    assert counts(result)["claude_code"] is None
    assert counts(result)["acp"] == 1


def test_a_selector_the_runner_does_not_register_is_reported() -> None:
    result = check(
        FakeProfile(
            {"acp": [A], "claude_code": [B], "rest": [C]},
            registered=["local_stack", "runtime_acp"],
        )
    )

    (finding,) = result.findings
    assert "runtime_claude_code" in finding


def test_a_failed_listing_of_the_registered_selectors_is_a_finding() -> None:
    result = check(FakeProfile({"acp": [A], "claude_code": [B], "rest": [C]}, registered=None))

    assert result.findings
