"""The refill test does not depend on `WAIT` (spec: unit-scheduling).

`WAIT` is the short per-build bound of this pass's tests. A bound that runs out on a loaded
machine let the refill test release its builds before the next unit of the project had
started, which read as the pass refilling the wrong project. The refill test waits on events
now, and `HANG_GUARD` is the one bound it keeps, only so a hang ends. With `WAIT` at zero,
as it is when it has run out, the refill test must give the same result.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli import test_tick_scheduling_projects as scheduling
from tests.cli.test_tick_scheduling_projects import builder, isolated  # noqa: F401 — fixture

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_the_refill_test_gives_the_same_result_when_wait_has_run_out(
    builder: scheduling.Builder,  # noqa: F811 — the imported fixture
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduling, "WAIT", 0)

    scheduling.test_one_project_starts_its_next_unit_as_one_of_its_builds_ends_and_the_other_does_not(
        builder, tmp_path, monkeypatch
    )
