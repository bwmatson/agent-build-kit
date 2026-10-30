"""A test stopped by its time limit says where every thread was (spec: test-failure-evidence).

The plugin is driven in a child pytest over `tests/child_modules/time_limit_stacks/`, whose test
waits in one function while a worker thread waits in another.
"""

from __future__ import annotations

import pytest

from tests.child_pytest import run_scenario

SCENARIO = "time_limit_stacks"


def test_a_test_stopped_at_its_limit_has_the_stack_of_every_thread_after_the_limit_it_names(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_scenario(
        pytester, SCENARIO, "stuck.py", "--test-time-limit=1", monkeypatch=monkeypatch
    )

    assert result.code == 1, result.output
    assert "time limit of 1 seconds" in result.output, result.output
    assert "waiting_in_the_test_itself" in result.output, "the test's own thread"
    assert "parked_in_a_worker_thread" in result.output, "another thread"
    limit = result.output.index("test exceeded the time limit of 1 seconds")
    assert limit < result.output.index("parked_in_a_worker_thread"), result.output
