"""A branch holding a group's `feat:` where its `test:` belongs stops the unit naming that
commit, whatever is on the branch after it (spec: built-group-recorded-as-empty-pair)."""

from __future__ import annotations

from pathlib import Path

from tests.factories import git
from tests.graph.branch_fakes import built, prepared, titled
from tests.graph.test_build_path import build

LONE = "a feat: commit for group 4 has no test: commit before it (feat: G4)"
GROUPS = {"add-marker": titled(3, 4)}
SEEDED = ["test: G3", "feat: G3", "feat: G4"]


def marked_empty(repo: Path) -> None:
    for subject in ("test: G4", "feat: G4"):
        message = f"{subject}\n\nUnit: add-marker/1\nAlready-built: yes\n"
        git(repo, "commit", "-q", "--allow-empty", "-m", message)


def test_a_lone_feat_stops_the_unit_naming_it(tmp_path: Path) -> None:
    _, outcome, _ = built(tmp_path, groups=GROUPS, seeded=SEEDED)

    assert outcome.status == "failed"
    assert LONE in outcome.detail
    assert f"the branch holds no {LONE}" not in outcome.detail


def test_the_stop_is_the_same_with_an_empty_marked_pair_after_the_lone_feat(
    tmp_path: Path,
) -> None:
    recorder, _ = prepared(
        tmp_path, groups=GROUPS, seeded=SEEDED, silent_groups=(4,), meanwhile=marked_empty
    )

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert LONE in outcome.detail
    assert f"the branch holds no {LONE}" not in outcome.detail
