"""The metrics catalogue reads the helper's calls as it reads the direct ones
(spec: dry-cleanup, the metrics page still lists the instruments the helper emits)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.serve.metrics import Instrument, catalogue

# The four instruments the move must keep listed, as their call sites spell them now.
CALLS = {
    "abk.tick.duration": (
        'emit_metric("duration", "abk.tick.duration", elapsed, log, outcome=tick.outcome)',
        Instrument(name="abk.tick.duration", type="histogram", attributes=("outcome",), unit="s"),
    ),
    "abk.usage.pauses": (
        'emit_metric("count", "abk.usage.pauses", 1, say, unit=u, change=c, kind="usage")',
        Instrument(name="abk.usage.pauses", type="counter", attributes=("kind",)),
    ),
    "abk.unit.duration": (
        "labels = {'repo': r, 'tier': t, 'outcome': o}\n"
        '    emit_metric("duration", "abk.unit.duration", 3.0, log, unit=u, change=c, **labels)',
        Instrument(
            name="abk.unit.duration",
            type="histogram",
            attributes=("repo", "tier", "outcome"),
            unit="s",
        ),
    ),
    "abk.review.rounds": (
        'emit_metric("observe", "abk.review.rounds", 2, log, unit=u, change=c, repo=r, outcome=o)',
        Instrument(name="abk.review.rounds", type="histogram", attributes=("repo", "outcome")),
    ),
}


@pytest.mark.parametrize("name", sorted(CALLS))
def test_an_instrument_emitted_through_the_helper_is_listed_with_its_type_and_attributes(
    tmp_path: Path, name: str
) -> None:
    call, expected = CALLS[name]
    (tmp_path / "site.py").write_text(f"def site(log):\n    {call}\n")

    assert catalogue(tmp_path) == [expected]


def test_a_helper_call_and_a_direct_call_to_one_name_merge_their_attributes(
    tmp_path: Path,
) -> None:
    (tmp_path / "site.py").write_text(
        "def a(log):\n"
        '    emit_metric("count", "abk.usage.pauses", 1, log, kind="usage")\n'
        "def b():\n"
        '    telemetry.count("abk.usage.pauses", reason="x")\n'
    )

    (listed,) = catalogue(tmp_path)

    assert (listed.type, listed.attributes) == ("counter", ("kind", "reason"))


def test_a_helper_call_with_a_computed_name_is_not_an_instrument(tmp_path: Path) -> None:
    (tmp_path / "site.py").write_text(
        'def site(log, name):\n    emit_metric("count", name, 1, log, kind="usage")\n'
        '    emit_metric("count", "other", 1, log, kind="usage")\n'
        '    emit_metric("count", "abk.real", 1, log, kind="usage")\n'
    )

    assert [i.name for i in catalogue(tmp_path)] == ["abk.real"]


# What the package's own call sites make of each instrument, read from the real source.
PACKAGE = [
    Instrument(name="abk.tick.duration", type="histogram", attributes=("outcome",), unit="s"),
    Instrument(name="abk.usage.pauses", type="counter", attributes=("kind",)),
    Instrument(
        name="abk.unit.duration",
        type="histogram",
        attributes=("repo", "tier", "outcome"),
        unit="s",
    ),
    Instrument(name="abk.review.rounds", type="histogram", attributes=("repo", "outcome")),
    Instrument(name="abk.checks.failures", type="counter", attributes=("check", "round")),
]


@pytest.mark.parametrize("expected", PACKAGE, ids=lambda i: i.name)
def test_the_package_catalogue_lists_each_moved_instrument_as_it_was(expected: Instrument) -> None:
    listed = {i.name: i for i in catalogue()}

    assert listed[expected.name] == expected
