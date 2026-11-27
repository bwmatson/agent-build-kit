"""The commit-order check: tests exist first, and they failed first.

A unit's branch must read as tests-then-implementation (docs/architecture.md).
That is not a style preference: it is the only
evidence that a test can actually fail, and a test that never failed proves
nothing about the code it supposedly covers.

The structural half is checked here against real git repositories built in
tmp_path, because the rules are about commits and diffs — mocking git would
only test the mock.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.commit_order import (
    CHANGELOG_SEPARATED,
    STUB_BODY_HINT,
    adopted_names,
    branch_commit_subjects,
    branch_commit_trailers,
    branch_subjects,
    check_structure,
    classify_paths,
    extended_test_file,
    group_progress,
    stub_violations,
    superseded_pairs,
    walk_group_progress,
)
from agent_build_kit.pipeline.group_mode import GroupMode
from agent_build_kit.pipeline.group_paths import allows_tests_only
from agent_build_kit.pipeline.stack_runner import GroupStep
from agent_build_kit.profiles.python_uv import PROFILE
from tests.attach_driver import head
from tests.factories import commit_files as commit
from tests.factories import git, init_repo

CHANGE = "feature"


def step(number: int, title: str, mode: GroupMode = GroupMode.TESTS_AND_CODE) -> GroupStep:
    return GroupStep(change_dir=f"changes/{CHANGE}", number=number, title=title, mode=mode)


def grouped(repo: Path, subject: str, files: dict[str, str], group: str = "") -> None:
    """A commit with the unit's trailer and, when `group` is given, `Group: <change>/<group>`."""
    trailers = "Unit: feature/1" + (f"\nGroup: {CHANGE}/{group}" if group else "")
    commit(repo, f"{subject}\n\n{trailers}\n", files)


def stale_pair(repo: Path, number: int, old: str, new_feat: str | None = None) -> None:
    """Group `number`'s pair under its trailer, its `test:` titled `old` and its `feat:` titled
    `new_feat` (`old` too when not given)."""
    grouped(repo, f"test: {old}", {f"tests/test_{number}.py": "def test_x(): ...\n"}, str(number))
    grouped(repo, f"feat: {new_feat or old}", {f"src/mod_{number}.py": "x = 1\n"}, str(number))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "README.md").write_text("base\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-q", "-b", "spec/change/1-unit")
    return tmp_path


def test_tests_first_then_implementation_passes(repo: Path) -> None:
    commit(repo, "test: covers the thing", {"tests/test_thing.py": "def test_x(): assert False\n"})
    commit(repo, "feat: the thing", {"src/thing.py": "def x():\n    return 1\n"})

    assert check_structure(repo, "main") == []


def test_implementation_in_the_first_commit_is_rejected(repo: Path) -> None:
    """The failure this whole check exists to catch."""
    commit(
        repo,
        "feat: everything at once",
        {"src/thing.py": "def x():\n    return 1\n", "tests/test_thing.py": "def test_x(): ...\n"},
    )

    problems = check_structure(repo, "main")

    assert problems
    assert "first commit" in problems[0]


def test_a_branch_with_only_tests_is_rejected(repo: Path) -> None:
    """Tests with no implementation behind them is an unfinished unit, not a
    unit that happens to need no code."""
    commit(repo, "test: covers the thing", {"tests/test_thing.py": "def test_x(): ...\n"})

    problems = check_structure(repo, "main")

    assert problems
    assert "implementation" in problems[0]


def test_stubs_are_allowed_in_the_tests_commit(repo: Path) -> None:
    """A test importing a function that doesn't exist yet fails to import
    rather than failing an assertion, so a NotImplementedError stub is allowed
    to make the failure a real one."""
    commit(
        repo,
        "test: covers the thing",
        {
            "tests/test_thing.py": "from src.thing import x\n\ndef test_x(): assert x() == 1\n",
            "src/thing.py": "def x() -> int:\n    raise NotImplementedError\n",
        },
    )
    commit(repo, "feat: the thing", {"src/thing.py": "def x() -> int:\n    return 1\n"})

    assert check_structure(repo, "main") == []


def test_logic_disguised_as_a_stub_is_rejected(repo: Path) -> None:
    """Otherwise 'stubs allowed' becomes a hole big enough to drive the whole
    implementation through."""
    commit(
        repo,
        "test: covers the thing",
        {
            "tests/test_thing.py": "def test_x(): ...\n",
            "src/thing.py": "def x() -> int:\n    return 1\n",
        },
    )
    commit(repo, "feat: more", {"src/other.py": "y = 2\n"})

    problems = check_structure(repo, "main")

    # The headline says which rule broke; a later line names the file and
    # function, so a reviewer gets both the rule and the fix.
    assert "first commit" in problems[0]
    assert any(STUB_BODY_HINT in problem for problem in problems)
    assert any("src/thing.py" in problem for problem in problems)


def test_several_test_implementation_pairs_are_allowed(repo: Path) -> None:
    """A unit can absorb several task groups (§3.4.1.1), so the branch is a
    sequence of pairs rather than exactly one."""
    commit(repo, "test: one", {"tests/test_one.py": "def test_x(): ...\n"})
    commit(repo, "feat: one", {"src/one.py": "x = 1\n"})
    commit(repo, "test: two", {"tests/test_two.py": "def test_y(): ...\n"})
    commit(repo, "feat: two", {"src/two.py": "y = 2\n"})

    assert check_structure(repo, "main") == []


def test_two_test_commits_in_a_row_are_rejected(repo: Path) -> None:
    """Tests, tests, then code is not tests-first for the second batch: the
    second batch was written while the first implementation didn't exist."""
    commit(repo, "test: one", {"tests/test_one.py": "def test_x(): ...\n"})
    commit(repo, "test: two", {"tests/test_two.py": "def test_y(): ...\n"})
    commit(repo, "feat: both", {"src/both.py": "x = 1\n"})

    problems = check_structure(repo, "main")

    assert problems
    assert "in a row" in problems[0]


def test_docs_only_changes_ride_along_with_either_commit(repo: Path) -> None:
    """A README tweak is neither a test nor an implementation, and refusing it
    would push authors into a separate branch for a one-line doc fix."""
    commit(
        repo,
        "test: covers the thing",
        {"tests/test_thing.py": "def test_x(): ...\n", "README.md": "base\nmore\n"},
    )
    commit(repo, "feat: the thing", {"src/thing.py": "x = 1\n"})

    assert check_structure(repo, "main") == []


@pytest.mark.parametrize(
    "path,kind",
    [
        ("tests/test_thing.py", "test"),
        ("svc-a/tests/test_thing.py", "test"),
        ("tests/conftest.py", "test"),
        ("tests/fixtures/page.html", "test"),
        ("src/thing.py", "code"),
        ("README.md", "docs"),
        ("docs/design.md", "docs"),
        ("pyproject.toml", "code"),
    ],
)
def test_paths_are_classified_by_where_they_live(path: str, kind: str) -> None:
    assert classify_paths([path])[path] == kind


def test_the_three_readers_of_a_test_folder_agree_and_a_testing_folder_is_not_one() -> None:
    expected = {
        "pkg/tests/x.py": True,
        "web/src/test/api.ts": True,
        "web/src/__tests__/a.ts": True,
        "src/pkg/testing/helpers.py": False,
        "src/pkg/module.py": False,
    }

    commit_order = {p: classify_paths([p])[p] == "test" for p in expected}
    group_reading = {p: allows_tests_only([p]) for p in expected}
    profile = {p: PROFILE.is_test_path(p) for p in expected}

    assert commit_order == expected
    assert group_reading == expected
    assert profile == expected


@pytest.mark.parametrize(
    ("new", "held", "expected"),
    [
        (
            "t/test_units_in_progress.py",
            {"t/test_units.py", "t/test_units_in.py"},
            ("t/test_units.py", "units_in_progress"),
        ),
        (
            "web/units.label.test.ts",
            {"web/units.test.ts"},
            ("web/units.test.ts", "units.label"),
        ),
        ("t/test_units_x.py", {"other/test_units.py"}, None),
        ("t/test_units.py", {"t/test_units_x.py"}, None),
        ("t/helpers.py", {"t/test_units.py"}, None),
    ],
)
def test_the_test_file_a_new_one_extends_is_the_one_with_the_shortest_leading_subject(
    new: str, held: set[str], expected: tuple[str, str] | None
) -> None:
    assert extended_test_file(new, held.__contains__) == expected


def test_stub_detection_reads_python_bodies() -> None:
    stub = "def x() -> int:\n    raise NotImplementedError\n"
    documented_stub = 'def x() -> int:\n    """Docs."""\n    raise NotImplementedError\n'
    declaration = "from dataclasses import dataclass\n\n@dataclass\nclass P:\n    a: int\n"
    logic = "def x() -> int:\n    return 1\n"

    assert stub_violations("s.py", stub) == []
    assert stub_violations("s.py", documented_stub) == []
    assert stub_violations("s.py", declaration) == []
    assert stub_violations("s.py", logic) != []


def test_unparseable_python_is_not_treated_as_a_stub() -> None:
    """A syntax error can't be read, and 'can't tell' must not mean 'allowed'."""
    assert stub_violations("s.py", "def x(:\n") != []


def test_a_lockfile_only_commit_after_the_implementation_is_accepted(repo: Path) -> None:
    """A real build pushes one: the lockfile update lands after the implementation."""
    commit(
        repo,
        "test: Add marker()",
        {
            "src/app/marker.py": "def marker():\n    raise NotImplementedError\n",
            "tests/test_marker.py": "def test_marker(): assert False\n",
        },
    )
    commit(
        repo, "feat: Implement marker()", {"src/app/marker.py": "def marker():\n    return 'm'\n"}
    )
    commit(repo, "chore: Update the lockfile", {"uv.lock": "version = 1\n"})

    assert check_structure(repo, "main") == []


def test_a_pair_under_a_groups_trailer_with_an_older_title_is_counted_and_noted(
    repo: Path,
) -> None:
    stale_pair(repo, 1, "One")
    stale_pair(repo, 2, "Old two")

    progress = walk_group_progress(repo, "main", [step(1, "One"), step(2, "Two")])

    assert progress.done == 2
    assert len(progress.notes) == 1
    note = progress.notes[0]
    assert "test: Old two" in note
    assert "feat: Old two" in note
    assert "Two" in note


def test_a_pair_whose_titles_differ_under_one_trailer_passes_the_gates_pairing(repo: Path) -> None:
    stale_pair(repo, 1, "One")
    stale_pair(repo, 2, "Old two", new_feat="Two")

    problems = check_structure(repo, "main", paired=True, groups=[step(1, "One"), step(2, "Two")])

    assert problems == []


def test_a_commit_at_a_groups_place_with_another_groups_trailer_is_not_counted_for_it(
    repo: Path,
) -> None:
    stale_pair(repo, 1, "One")
    grouped(repo, "test: Two", {"tests/test_2.py": "def test_x(): ...\n"}, "3")
    grouped(repo, "feat: Two", {"src/mod_2.py": "x = 1\n"}, "3")

    progress = walk_group_progress(repo, "main", [step(1, "One"), step(2, "Two"), step(3, "Three")])

    assert progress.done == 1
    assert progress.notes == ()


def test_commits_with_no_group_trailer_give_the_walk_the_results_they_gave_before(
    repo: Path,
) -> None:
    commit(repo, "test: One", {"tests/test_1.py": "def test_x(): ...\n"})
    commit(repo, "feat: One", {"src/mod_1.py": "x = 1\n"})
    commit(repo, "test: Two", {"tests/test_2.py": "def test_x(): ...\n"})
    steps = [step(1, "One"), step(2, "Two")]

    walked = walk_group_progress(repo, "main", steps)

    assert walked == group_progress(branch_subjects(repo, "main"), ["One", "Two"])
    assert (walked.done, walked.tests_made, walked.notes) == (1, True, ())
    assert check_structure(repo, "main", paired=True, groups=steps) == check_structure(
        repo, "main", paired=True
    )


def test_a_refactor_groups_place_holding_a_tests_commit_under_its_own_trailer_is_not_counted(
    repo: Path,
) -> None:
    grouped(repo, "test: One", {"tests/test_1.py": "def test_x(): ...\n"}, "1")
    grouped(repo, "feat: One", {"src/mod_1.py": "x = 1\n"}, "1")

    progress = walk_group_progress(repo, "main", [step(1, "One", GroupMode.REFACTOR)])

    assert progress.done == 0


def test_an_adopted_commit_after_a_retitled_pair_is_named_for_the_next_group_by_subject_and_trailer(
    repo: Path,
) -> None:
    stale_pair(repo, 3, "Old G3")

    subject, group = adopted_names(
        "Unit",
        [step(3, "G3"), step(4, "G4")],
        branch_subjects(repo, "main"),
        branch_commit_trailers(repo, "main"),
    )

    assert (subject, group) == ("test: G4", f"{CHANGE}/4")


def pipeline_commit(repo: Path) -> None:
    commit(repo, CHANGELOG_SEPARATED, {"CHANGELOG.md": "## Unreleased\n\n- a\n\n- b\n"})


def two_groups_with_pipeline_commit_at(repo: Path, where: str) -> list[list[str]]:
    """Groups 1 and 2, each a trailer-less `test:`/`feat:` pair, with the pipeline's own commit
    `where`; the hashes of each group's pair."""
    if where == "before":
        pipeline_commit(repo)
    pairs: list[list[str]] = []
    for number in (1, 2):
        commit(repo, f"test: G{number}", {f"tests/test_{number}.py": "def test_x(): ...\n"})
        tests = head(repo)
        if where == f"between-{number}":
            pipeline_commit(repo)
        commit(repo, f"feat: G{number}", {f"src/mod_{number}.py": "x = 1\n"})
        pairs.append([tests, head(repo)])
    if where == "after":
        pipeline_commit(repo)
    return pairs


@pytest.mark.parametrize("where", ["between-1", "between-2", "before", "after"])
def test_a_pipeline_made_commit_is_not_part_of_any_group(repo: Path, where: str) -> None:
    pairs = two_groups_with_pipeline_commit_at(repo, where)
    steps = [step(1, "G1"), step(2, "G2")]

    progress = walk_group_progress(repo, "main", steps)
    superseded = superseded_pairs(
        repo, "HEAD", "main", ["G1", "G2"], [GroupMode.TESTS_AND_CODE] * 2
    )

    assert (progress.done, progress.tests_made, progress.notes) == (
        2,
        False,
        (),
    ), "walk_group_progress counted the pipeline commit"
    assert superseded == pairs, "superseded_pairs counted the pipeline commit"
    assert CHANGELOG_SEPARATED not in branch_subjects(repo, "main"), (
        "branch_subjects listed the pipeline commit"
    )
    assert check_structure(repo, "main", paired=True, groups=steps) == [], (
        "check_structure reported the pipeline commit"
    )
    assert adopted_names("Unit", steps, branch_subjects(repo, "main"), []) == (
        "fix: G2 (adopted)",
        f"{CHANGE}/2",
    ), "adopted_names counted the pipeline commit"


def test_a_pipeline_made_commit_leaves_the_hashes_and_subjects_aligned(repo: Path) -> None:
    pairs = two_groups_with_pipeline_commit_at(repo, "between-1")

    found = branch_commit_subjects(repo, "main")

    assert [sha for sha, _ in found] == [sha for pair in pairs for sha in pair]
    assert len(branch_commit_trailers(repo, "main")) == len(found)


A_TESTS = "def test_a():\n    assert False\n"
A_TESTS_FIXED = "def test_a():\n    assert 1 == 2\n"
A_CODE = "def a() -> int:\n    return 1\n"


def pair_then(repo: Path, feat: dict[str, str], later: dict[str, str] | None = None) -> None:
    """Group A's `test:` commit, its `feat:` commit with these files and, when given, a
    `fix:` commit after them with `later`."""
    commit(repo, "test: A", {"tests/test_a.py": A_TESTS})
    commit(repo, "feat: A", feat)
    if later is not None:
        commit(repo, "fix: A (review round 1)", later)


# (the build mode of group A, the commits after the base, the file the one problem names)
TEST_EDITS = [
    pytest.param(
        GroupMode.TESTS_AND_CODE,
        {"feat": {"src/a.py": A_CODE, "tests/test_a.py": A_TESTS_FIXED}},
        "tests/test_a.py",
        id="a feat commit of a group with a tests step that changes a test file",
    ),
    pytest.param(
        GroupMode.TESTS_AND_CODE,
        {"feat": {"src/a.py": A_CODE, "tests/conftest.py": "import pytest\n"}},
        "tests/conftest.py",
        id="a feat commit that changes conftest.py",
    ),
    pytest.param(
        GroupMode.TESTS_AND_CODE,
        {"feat": {"src/a.py": A_CODE}},
        None,
        id="a feat commit that changes only code",
    ),
    pytest.param(
        GroupMode.TESTS_AND_CODE,
        {
            "feat": {"src/a.py": "def a() -> int:\n    raise NotImplementedError\n"},
            "later": {"src/a.py": A_CODE, "tests/test_a.py": A_TESTS_FIXED},
        },
        None,
        id="a fix commit after the pair that changes code and a test file",
    ),
]


@pytest.mark.parametrize(("mode", "commits", "named"), TEST_EDITS)
def test_a_feat_commit_of_a_group_with_a_tests_step_touches_no_test_file(
    repo: Path, mode: GroupMode, commits: dict[str, dict[str, str]], named: str | None
) -> None:
    pair_then(repo, commits["feat"], commits.get("later"))

    problems = check_structure(repo, "main", paired=True, groups=[step(1, "A", mode)])

    if named is None:
        assert problems == []
        return
    assert len(problems) == 1
    assert "feat: A" in problems[0]
    assert named in problems[0]
    assert "test:" in problems[0]
    assert not any(STUB_BODY_HINT in problem for problem in problems)


def test_a_commit_with_any_other_subject_between_a_pair_still_breaks_it(repo: Path) -> None:
    commit(repo, "test: G1", {"tests/test_1.py": "def test_x(): ...\n"})
    commit(repo, "docs: Reword the readme", {"README.md": "reworded\n"})
    commit(repo, "feat: G1", {"src/mod_1.py": "x = 1\n"})

    progress = walk_group_progress(repo, "main", [step(1, "G1")])

    assert (progress.done, progress.tests_made) == (0, True)
