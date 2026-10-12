"""The reference matcher implements the documented glob dialect, and the shipped
list is the one the test writes out."""

from __future__ import annotations

import pytest

from agent_build_kit.runtimes.recommended_policy import DIALECT, RECOMMENDED, matches, patterns

PUSH_MAIN = "git push origin main"
REFSPEC = "git push *[ +:\"']main"

GLOBS = [
    # merging a pull request
    "gh pr merge",
    "gh pr merge *",
    "gh * pr merge",
    "gh * pr merge *",
    # merging through the host's raw API
    "gh api *pulls/*/merge*",
    "gh * api *pulls/*/merge*",
    # merging through the host's GraphQL API
    "gh api graphql *mergePullRequest*",
    "gh * api graphql *mergePullRequest*",
    # amending a commit
    "git commit *--amend*",
    "git * commit *--amend*",
    "git amend",
    "git amend *",
    # pushing to the default branch, under both prefixes
    "git push *[ +:\"']main",
    "git push *[ +:\"']main *",
    "git push *[ +:\"']main[\"']*",
    "git push *heads/main",
    "git push *heads/main *",
    "git push *heads/main[\"']*",
    "git push *[ +:\"']master",
    "git push *[ +:\"']master *",
    "git push *[ +:\"']master[\"']*",
    "git push *heads/master",
    "git push *heads/master *",
    "git push *heads/master[\"']*",
    "git * push *[ +:\"']main",
    "git * push *[ +:\"']main *",
    "git * push *[ +:\"']main[\"']*",
    "git * push *heads/main",
    "git * push *heads/main *",
    "git * push *heads/main[\"']*",
    "git * push *[ +:\"']master",
    "git * push *[ +:\"']master *",
    "git * push *[ +:\"']master[\"']*",
    "git * push *heads/master",
    "git * push *heads/master *",
    "git * push *heads/master[\"']*",
]


def test_the_dialect_is_documented_in_a_sentence_each_for_the_four_rules() -> None:
    lowered = DIALECT.lower()
    for word in ("case", "segment", "anchor", "whitespace"):
        assert word in lowered, word


@pytest.mark.parametrize("command", ["GIT PUSH ORIGIN MAIN", "Git Push Origin Main"])
def test_the_matcher_ignores_letter_case(command: str) -> None:
    assert matches(PUSH_MAIN, command)
    assert matches("GIT PUSH ORIGIN MAIN", PUSH_MAIN)


def test_the_matcher_collapses_runs_of_whitespace() -> None:
    assert matches(PUSH_MAIN, "git   push  origin    main")
    assert matches(PUSH_MAIN, "git push\t origin main")
    assert matches("git   push origin main", PUSH_MAIN)


@pytest.mark.parametrize("operator", ["&&", "||", "|", ";"])
def test_the_matcher_matches_a_segment_after_each_operator(operator: str) -> None:
    assert matches(PUSH_MAIN, f"echo start {operator} {PUSH_MAIN}")
    assert matches(PUSH_MAIN, f"echo start{operator}{PUSH_MAIN}")
    assert matches(PUSH_MAIN, f"{PUSH_MAIN} {operator} echo done")


def test_the_matcher_matches_a_segment_after_a_newline() -> None:
    assert matches(PUSH_MAIN, f"echo start\n{PUSH_MAIN}")
    assert matches(PUSH_MAIN, f"echo start\n{PUSH_MAIN}\necho done")


@pytest.mark.parametrize("prefix", ["sudo ", "env X=1 ", "command ", "time ", "echo "])
def test_the_matcher_anchors_at_the_start_of_the_command(prefix: str) -> None:
    assert not matches(PUSH_MAIN, f"{prefix}{PUSH_MAIN}")


def test_the_matcher_anchors_at_the_end_of_the_command() -> None:
    assert not matches(PUSH_MAIN, "git push origin main now")
    assert not matches("git push", PUSH_MAIN)


def test_a_star_crosses_spaces_and_slashes() -> None:
    assert matches("git *main", "git push origin refs/heads/main")
    assert matches("gh api *pulls/*/merge*", "gh api -X PUT repos/o/r/pulls/1/merge?m=squash")
    assert matches("a*z", "a b/c d z")


@pytest.mark.parametrize("before", [" ", "+", ":", '"', "'"])
def test_the_class_of_space_plus_colon_and_quotes_matches_each_member(before: str) -> None:
    assert matches(REFSPEC, f"git push origin{before}main")
    assert matches("a[ +:\"']b", f"a{before}b")


@pytest.mark.parametrize("letter", ["x", "/", "-"])
def test_the_class_matches_nothing_outside_its_members(letter: str) -> None:
    assert not matches(REFSPEC, f"git push origin{letter}main")
    assert not matches("a[ +:]b", f"a{letter}b")


def test_a_question_mark_matches_one_character() -> None:
    assert matches("git push origin mai?", PUSH_MAIN)
    assert not matches("git push origin mai?", "git push origin mai")


def test_the_list_has_no_duplicate_and_no_blank_entry() -> None:
    assert RECOMMENDED, "the table is empty"
    listed = patterns()
    assert len(listed) == len(set(listed))
    assert all(entry.strip() for entry in listed)


def test_the_list_is_in_table_order() -> None:
    assert RECOMMENDED, "the table is empty"
    in_order = list(dict.fromkeys(glob for policy in RECOMMENDED for glob in policy.globs))
    assert patterns() == in_order


def test_a_caller_s_extra_patterns_follow_the_list_and_none_is_repeated() -> None:
    base = patterns()
    assert patterns(["deploy *", "deploy *", base[0], "release *"]) == [
        *base,
        "deploy *",
        "release *",
    ]
    assert patterns(()) == base


def test_the_list_equals_the_one_written_in_the_test() -> None:
    assert patterns() == GLOBS
