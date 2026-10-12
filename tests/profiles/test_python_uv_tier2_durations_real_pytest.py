"""What the pinned pytest prints for durations under the tier 2 flags, read by the profile.

The parser and the stripper are checked against a real run, since a change in the header,
the entry layout or the note of hidden entries would otherwise leave every result with no
durations and nothing failing.
"""

import pytest

from agent_build_kit.profiles.python_uv import PROFILE

TESTS = """\
import pytest

pytestmark = pytest.mark.local_stack


@pytest.fixture
def made():
    return 1


def test_one(made):
    pass


def test_two():
    pass
"""


def _run(pytester: pytest.Pytester, *extra: str) -> str:
    pytester.makeini("[pytest]\nmarkers =\n    local_stack: needs the live stack\n")
    pytester.makepyfile(test_live=TESTS)
    (command,) = PROFILE.tier2_commands(pytester.path, marker="local_stack")
    result = pytester.runpytest_subprocess(*command[command.index("pytest") + 1 :], *extra)
    return result.stdout.str()


def test_the_one_second_floor_leaves_fast_tests_out_under_the_tier_2_flags(
    pytester: pytest.Pytester,
) -> None:
    output = _run(pytester)

    assert PROFILE.parse_test_durations(output) == []
    assert "2 passed in" in output


def test_every_phase_of_every_test_is_one_entry_when_the_floor_is_lifted(
    pytester: pytest.Pytester,
) -> None:
    output = _run(pytester, "--durations-min=0")

    found = PROFILE.parse_test_durations(output)
    assert len(found) == len({(e.test, e.phase) for e in found})
    assert {e.test for e in found} == {"test_live.py::test_one", "test_live.py::test_two"}
    assert {e.phase for e in found} <= {"setup", "call", "teardown"}
    assert {(e.test, e.phase) for e in found} == {
        (test, phase)
        for test in ("test_live.py::test_one", "test_live.py::test_two")
        for phase in ("setup", "call", "teardown")
    }
    kept = PROFILE.without_durations(output)
    assert "slowest durations" not in kept
    assert not [line for line in kept.splitlines() if line.endswith("test_live.py::test_one")]
    assert "2 passed in" in kept
