"""A tier 1 failure is classified once at each site that records it, and telemetry and
the local record carry that one result (spec: dry-cleanup, a failure is classified once).

The two sites are the checks after the build and the whole-repo run for a unit that
produced nothing of its own. The tick runs through `cmd_tick` with telemetry on; the
classification is counted at the toolchain profile, where it is made.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from agent_build_kit.pipeline.metric_records import read_metrics
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.cli.test_tick_telemetry import (  # noqa: F401 — fixtures
    FAILING,
    Ticks,
    exported,
    ticks,
)
from tests.otlp import Collector


def fail_checks(ticks: Ticks) -> None:  # noqa: F811
    """Tier 1 fails once after the build, then passes."""
    ticks.recorder.tier1_results = [(False, FAILING), (True, "")]
    ticks.agents()


def fail_whole_repo(ticks: Ticks) -> None:  # noqa: F811
    """The branch holds nothing of the unit's own, so tier 1 runs on the whole repo."""
    ticks.options["branch_commits"] = lambda cwd, base: 0
    ticks.recorder.tier1_results = [(False, FAILING)]


SITES = [pytest.param(fail_checks, id="checks"), pytest.param(fail_whole_repo, id="tier1")]


def classifying(
    monkeypatch: pytest.MonkeyPatch, answer: Callable[[str], str] | None = None
) -> list[str]:
    """Count the profile's classifications; `answer` replaces the profile's own reading."""
    asked: list[str] = []
    real = PythonUvProfile.failure_kind

    def failure_kind(self: Any, output: str) -> str:
        asked.append(output)
        return answer(output) if answer else real(self, output)

    monkeypatch.setattr(PythonUvProfile, "failure_kind", failure_kind)
    return asked


def exported_and_recorded(ticks: Ticks, exported: Collector) -> tuple[set[Any], set[Any]]:  # noqa: F811
    points = {p.attributes["check"] for p in exported.metric("abk.checks.failures")}
    records = {
        r.attributes["check"]
        for r in read_metrics(ticks.inst.state_dir / LEDGER_NAME)
        if r.metric == "abk.checks.failures"
    }
    return points, records


@pytest.mark.parametrize("fail", SITES)
def test_a_tier_1_failure_is_classified_once_and_telemetry_and_the_record_agree(
    ticks: Ticks,  # noqa: F811
    exported: Collector,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    fail: Callable[[Ticks], None],
) -> None:
    asked = classifying(monkeypatch)
    fail(ticks)

    ticks.tick()

    assert len(asked) == 1
    assert exported_and_recorded(ticks, exported) == ({"types"}, {"types"})


@pytest.mark.parametrize("fail", SITES)
def test_a_classification_that_fails_falls_back_to_unknown_for_both(
    ticks: Ticks,  # noqa: F811
    exported: Collector,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    fail: Callable[[Ticks], None],
) -> None:
    def unreadable(output: str) -> str:
        raise ValueError("a hook this profile does not know")

    asked = classifying(monkeypatch, unreadable)
    fail(ticks)

    ticks.tick()

    assert len(asked) == 1
    assert exported_and_recorded(ticks, exported) == ({"unknown"}, {"unknown"})
