"""Agreement below the minimum over the most recent window of samples demotes the class."""

from __future__ import annotations

from pathlib import Path

from tests.demotion_triggers_support import evaluate, samples

CLEAN = "clean"
REWORKED = "reworked"


def test_eight_accepted_of_the_last_ten_demotes_with_the_agreement_trigger(
    tmp_path: Path,
) -> None:
    units, records = samples(*[CLEAN] * 8, *[REWORKED] * 2)

    demoted = evaluate(tmp_path, units, records)

    assert list(demoted) == ["docs"]
    assert [t["trigger"] for t in demoted["docs"]["triggers"]] == ["agreement"]


def test_nine_accepted_of_ten_does_not_demote(tmp_path: Path) -> None:
    units, records = samples(*[CLEAN] * 9, REWORKED)

    assert evaluate(tmp_path, units, records) == {}


def test_three_samples_none_accepted_does_not_demote_with_the_default_minimum(
    tmp_path: Path,
) -> None:
    units, records = samples(*[REWORKED] * 3)

    assert evaluate(tmp_path, units, records) == {}


def test_records_without_the_brief_are_not_counted(tmp_path: Path) -> None:
    units, records = samples(*[REWORKED] * 10, brief=False)

    assert evaluate(tmp_path, units, records) == {}


def test_older_samples_beyond_the_window_do_not_demote(tmp_path: Path) -> None:
    # Six rejected, then ten accepted: all sixteen would demote, the last ten do not.
    units, records = samples(*[REWORKED] * 6, *[CLEAN] * 10)

    assert evaluate(tmp_path, units, records) == {}


def test_the_most_recent_ten_demote_though_all_samples_together_would_not(
    tmp_path: Path,
) -> None:
    # Ten accepted, then eight of ten: eighteen of twenty is not below 0.9, the last ten are.
    units, records = samples(*[CLEAN] * 10, *[CLEAN] * 8, *[REWORKED] * 2)

    assert list(evaluate(tmp_path, units, records)) == ["docs"]
