"""The push gate, end to end.

`check_branch` is the one call the PreToolUse hook makes, so these tests build
real branches and let it run real commands in a real worktree. The commands
are cheap stand-ins for pre-commit and pytest, injected by monkeypatching the
two command templates — running the actual tools here would test uv's cache
more than it tests the gate.
"""

import shlex
from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.check_runner import CheckCache
from agent_build_kit.pipeline.gate import check_branch, red_problems
from agent_build_kit.pipeline.red_check import Rule
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON
from tests.factories import commit_files as commit
from tests.factories import git, init_repo
from tests.junit_cases import failing, passing, printed
from tests.whole_lines import assert_tail_of_whole_lines


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    (work / "README.md").write_text("base\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    git(work, "checkout", "-q", "-b", "spec/change/1-unit")
    return work


def tests_first_branch(repo: Path) -> None:
    commit(repo, "test: covers it", {"tests/test_thing.py": "def test_x(): assert False\n"})
    commit(repo, "feat: implements it", {"src/thing.py": "x = 1\n"})


@pytest.fixture
def fake_commands(monkeypatch: pytest.MonkeyPatch):
    """Stand in for pre-commit and pytest with scripted output."""

    def configure(*, clean_exit: int = 0, red_output: str, red_exit: int = 1) -> None:
        class Scripted:
            """The Python profile with its two shell-outs replaced."""

            def clean_command(self) -> str:
                return f"exit {clean_exit}"

            def red_command(
                self, files: list[str], ids: list[str] | None = None, **_: object
            ) -> str:
                return f"printf '%s' {red_output!r} && exit {red_exit}"

            def __getattr__(self, name):
                return getattr(PYTHON, name)

        monkeypatch.setattr(profiles, "get", lambda name: Scripted())

    return configure


FAILED = "1 failed in 0.01s\nFAILED tests/test_thing.py::test_x - assert 0 == 1\n"
PASSED = "2 passed in 0.01s\n"


def test_a_well_formed_branch_passes(repo: Path, fake_commands) -> None:
    tests_first_branch(repo)
    fake_commands(red_output=FAILED)

    assert check_branch(repo, "main") == []


def test_a_structural_problem_short_circuits(repo: Path, fake_commands) -> None:
    """If the shape is wrong, "which commit is the tests commit" isn't a
    meaningful question yet, so nothing is run."""
    commit(repo, "feat: all at once", {"src/thing.py": "def x():\n    return 1\n"})
    fake_commands(red_output=PASSED)

    problems = check_branch(repo, "main")

    assert problems
    assert "first commit" in problems[0] or "no implementation" in problems[0]


def test_tests_that_passed_at_the_tests_commit_block_the_push(repo: Path, fake_commands) -> None:
    """The case the gate exists for."""
    tests_first_branch(repo)
    fake_commands(red_output=PASSED, red_exit=0)

    problems = check_branch(repo, "main")

    assert any("passed at the tests commit" in problem for problem in problems)


def test_lint_failing_at_the_tests_commit_blocks_the_push(repo: Path, fake_commands) -> None:
    tests_first_branch(repo)
    fake_commands(clean_exit=1, red_output=FAILED)

    problems = check_branch(repo, "main")

    assert any("lint/format" in problem for problem in problems)


def test_the_lint_output_at_the_tests_commit_is_the_end_of_it_in_whole_lines(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    printed = [f"src/module_{n:04d}.py:1:1: F401 imported but unused" for n in range(200)]

    class Linting:
        def clean_command(self) -> str:
            return f"printf '%s\\n' {shlex.join(printed)}; exit 1"

        def red_command(self, files: list[str], ids: list[str] | None = None, **_: object) -> str:
            return f"printf '%s' {FAILED!r}; exit 1"

        def __getattr__(self, name):
            return getattr(PYTHON, name)

    monkeypatch.setattr(profiles, "get", lambda name: Linting())
    tests_first_branch(repo)

    (problem,) = [p for p in check_branch(repo, "main") if "lint/format" in p]

    shown = problem.splitlines()
    assert_tail_of_whole_lines("\n".join(shown[1:]), printed, 2000)
    assert 30 < len(shown) <= 2000 // len(printed[0]) + 2


THING = "tests/test_thing.py"
HELPERS = "tests/test_helpers.py"
MODULE = "tests.test_thing"
FAILS = "\n\ndef test_new_fails():\n    assert False\n"
NEW_FAILS = [failing(MODULE, "test_new_fails")]


def source_of(name: str, *body: str) -> str:
    return f"import pytest\n\n\ndef {name}:\n" + "".join(f"    {line}\n" for line in body)


def rule_line(test: str, rule: Rule, may_pass: bool, file: str = THING) -> str:
    return f"{file}::{test}: {rule.value}: {'may pass' if may_pass else 'must fail'}"


def logged_line(test: str, rule: Rule, outcome: str, file: str = THING) -> str:
    """The whole line the red run's log holds for a test: its rule and how it came out."""
    return f"{rule_line(test, rule, not rule.must_fail, file)} — {outcome}"


ARRANGED = source_of("test_x()", "items = [1, 2]", "assert len(items) == 2")
ASSERTS = source_of("test_x()", "value = 2", "assert value == 2")
PARAMS = (
    "import pytest\n\n\n@pytest.mark.parametrize('v', [1, 2{extra}])\n"
    "def test_p(v):\n    assert v > 0\n"
)
PARAM_CASES = [passing(MODULE, "test_p[1]"), passing(MODULE, "test_p[2]")]

# (files before, files after, the report the red run prints, problems it names, log lines it names)
JUDGED = [
    pytest.param(
        {THING: ASSERTS},
        {THING: ASSERTS + "\n\ndef test_new():\n    assert True\n" + FAILS},
        [passing(MODULE, "test_new"), *NEW_FAILS],
        [rule_line("test_new", Rule.NEW, False)],
        [],
        id="a new test that passes is rejected as new",
    ),
    pytest.param(
        {THING: ASSERTS},
        {THING: source_of("test_x()", "value = 2", "assert value == 3") + FAILS},
        [passing(MODULE, "test_x"), *NEW_FAILS],
        [rule_line("test_x", Rule.ASSERTION_CHANGED, False)],
        [],
        id="a changed expected value that passes is rejected as a changed assertion",
    ),
    pytest.param(
        {THING: ASSERTS},
        {THING: source_of("test_x()", "value = 2", "assert value == 2", "assert value") + FAILS},
        [passing(MODULE, "test_x"), *NEW_FAILS],
        [rule_line("test_x", Rule.ASSERTION_CHANGED, False)],
        [],
        id="an added assert that passes is rejected as a changed assertion",
    ),
    pytest.param(
        {THING: ASSERTS},
        {
            THING: source_of(
                "test_x()",
                "value = 2",
                "assert value == 2",
                "with pytest.raises(KeyError):",
                "    {}[1]",
            )
            + FAILS
        },
        [passing(MODULE, "test_x"), *NEW_FAILS],
        [rule_line("test_x", Rule.ASSERTION_CHANGED, False)],
        [],
        id="an added pytest.raises that passes is rejected as a changed assertion",
    ),
    pytest.param(
        {THING: source_of("test_x()", "assert 1.5 == pytest.approx(1.5)")},
        {THING: source_of("test_x()", "assert 1.5 == pytest.approx(1.6, abs=0.2)") + FAILS},
        [passing(MODULE, "test_x"), *NEW_FAILS],
        [rule_line("test_x", Rule.ASSERTION_CHANGED, False)],
        [],
        id="a changed approx check that passes is rejected as a changed assertion",
    ),
    pytest.param(
        {THING: ARRANGED},
        {THING: source_of("test_x()", "items = [3, 4]", "assert len(items) == 2") + FAILS},
        [passing(MODULE, "test_x"), *NEW_FAILS],
        [],
        [logged_line("test_x", Rule.CHANGED, "passed")],
        id="changed arranged values may pass beside a failing new test",
    ),
    pytest.param(
        {THING: ARRANGED},
        {THING: source_of("test_x(tmp_path)", "items = [1, 2]", "assert len(items) == 2") + FAILS},
        [passing(MODULE, "test_x"), *NEW_FAILS],
        [],
        [logged_line("test_x", Rule.CHANGED, "passed")],
        id="a changed fixture argument may pass beside a failing new test",
    ),
    pytest.param(
        {THING: ARRANGED},
        {THING: source_of("test_y()", "items = [1, 2]", "assert len(items) == 2") + FAILS},
        [passing(MODULE, "test_y"), *NEW_FAILS],
        [],
        [logged_line("test_y", Rule.RENAMED, "passed")],
        id="a renamed test may pass beside a failing new test",
    ),
    pytest.param(
        {THING: source_of("test_x()", "assert 1", "assert 2")},
        {THING: source_of("test_x()", "assert 1") + FAILS},
        [passing(MODULE, "test_x"), *NEW_FAILS],
        [],
        [logged_line("test_x", Rule.CHANGED, "passed")],
        id="a removed assert may pass beside a failing new test",
    ),
    pytest.param(
        {THING: ASSERTS},
        {THING: source_of("test_x()", "value = 2", "assert (value ==\n        2)") + FAILS},
        [passing(MODULE, "test_x"), *NEW_FAILS],
        [],
        [logged_line("test_x", Rule.CHANGED, "passed")],
        id="a reformatted assert is not a changed assertion",
    ),
    pytest.param(
        {THING: PARAMS.format(extra="")},
        {THING: PARAMS.format(extra=", -3") + FAILS},
        [*PARAM_CASES, failing(MODULE, "test_p[-3]")],
        [],
        [logged_line("test_p", Rule.ASSERTION_CHANGED, "failed")],
        id="a new parametrize row that fails beside old rows that pass is accepted",
    ),
    pytest.param(
        {THING: PARAMS.format(extra="")},
        {THING: PARAMS.format(extra=", 3")},
        [*PARAM_CASES, passing(MODULE, "test_p[3]")],
        [rule_line("test_p", Rule.ASSERTION_CHANGED, False)],
        [],
        id="a new parametrize row whose cases all pass is rejected",
    ),
    pytest.param(
        {
            THING: ASSERTS,
            HELPERS: "def helper():\n    return 1\n\n\ndef test_h():\n    assert helper()\n",
        },
        {
            THING: ASSERTS + FAILS,
            HELPERS: "def helper():\n    return 2\n\n\ndef test_h():\n    assert helper()\n",
        },
        [passing("tests.test_helpers", "test_h"), *NEW_FAILS],
        [],
        [logged_line("test_h", Rule.WITH_FILE, "passed", HELPERS)],
        id="a test in a file run whole may pass beside a failing selected test",
    ),
    pytest.param(
        {THING: ARRANGED},
        {THING: source_of("test_x()", "items = [3, 4]", "assert len(items) == 2")},
        [passing(MODULE, "test_x")],
        ["nothing failed"],
        [logged_line("test_x", Rule.CHANGED, "passed")],
        id="a commit in which nothing fails is rejected",
    ),
    pytest.param(
        {THING: ARRANGED},
        {
            THING: source_of("test_x()", "items = [3, 4]", "assert len(items) == 2")
            + "\n\ndef test_new():\n    assert True\n"
            + FAILS
        },
        [passing(MODULE, "test_x"), passing(MODULE, "test_new"), *NEW_FAILS],
        [rule_line("test_new", Rule.NEW, False)],
        [logged_line("test_x", Rule.CHANGED, "passed")],
        id="a rejection names the new test as one that must fail and the changed one as may pass",
    ),
]


@pytest.mark.parametrize(("before", "after", "cases", "named", "logged"), JUDGED)
def test_each_touched_test_is_judged_by_its_rule(
    repo: Path,
    fake_commands,
    before: dict[str, str],
    after: dict[str, str],
    cases: list[tuple[str, str, str | None]],
    named: list[str],
    logged: list[str],
) -> None:
    git(repo, "checkout", "-q", "main")
    commit(repo, "test: the tests that exist", before)
    git(repo, "checkout", "-q", "-B", "spec/change/1-unit")
    commit(repo, "test: covers it", after)
    commit(repo, "feat: implements it", {"src/thing.py": "x = 1\n"})
    fake_commands(red_output=printed(cases))
    log: list[str] = []

    problems = check_branch(repo, "main", log=log.append)

    assert bool(problems) == bool(named)
    for line in named:
        assert any(line in problem for problem in problems), problems
    for line in logged:
        assert any(line in logged_line for logged_line in log), log


def test_a_cached_pass_skips_the_work(repo: Path, fake_commands, tmp_path: Path) -> None:
    """A restack re-pushes commits whose content nothing has changed; re-running
    the suite for each of them would make every restack slower than the work."""
    tests_first_branch(repo)
    cache = CheckCache(tmp_path / "cache.json")
    fake_commands(red_output=FAILED)
    assert check_branch(repo, "main", cache=cache) == []

    # Now make the commands fail loudly: a cache hit means they never run.
    fake_commands(clean_exit=1, red_output=PASSED, red_exit=0)

    assert check_branch(repo, "main", cache=cache) == []


def test_a_cached_failure_still_blocks(repo: Path, fake_commands, tmp_path: Path) -> None:
    tests_first_branch(repo)
    cache = CheckCache(tmp_path / "cache.json")
    fake_commands(red_output=PASSED, red_exit=0)
    assert check_branch(repo, "main", cache=cache) != []

    fake_commands(red_output=FAILED)

    assert check_branch(repo, "main", cache=cache) != []


def test_a_pass_recorded_under_the_earlier_gate_label_is_not_reused(
    repo: Path, fake_commands, tmp_path: Path
) -> None:
    """A verdict recorded when every passing test was a problem was judged by another rule."""
    tests_first_branch(repo)
    cache = CheckCache(tmp_path / "cache.json")
    cache.record(repo, git(repo, "rev-parse", "HEAD~1").strip(), ok=True, mode="")
    fake_commands(red_output=PASSED, red_exit=0)

    problems = check_branch(repo, "main", cache=cache)

    assert any("passed at the tests commit" in problem for problem in problems), problems


@pytest.mark.parametrize("old_mode", ["red", "red-stubbed"])
def test_a_red_pass_recorded_under_the_earlier_label_is_not_reused(
    repo: Path, fake_commands, tmp_path: Path, old_mode: str
) -> None:
    tests_first_branch(repo)
    sha = git(repo, "rev-parse", "HEAD~1").strip()
    cache = CheckCache(tmp_path / "cache.json")
    cache.record(repo, sha, ok=True, mode=old_mode)
    fake_commands(red_output=PASSED, red_exit=0)

    problems = red_problems(
        repo, sha, profile=profiles.get("python-uv"), cache=cache, stubbed=old_mode != "red"
    )

    assert problems


def test_the_gate_does_not_touch_the_working_tree(repo: Path, fake_commands) -> None:
    """A gate that edits what it is judging is no longer a gate."""
    tests_first_branch(repo)
    fake_commands(red_output=FAILED)

    check_branch(repo, "main")

    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "spec/change/1-unit"
