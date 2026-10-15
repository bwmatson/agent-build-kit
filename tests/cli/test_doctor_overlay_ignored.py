"""`abk doctor`'s `public content` check on `abk.local.yaml`: it must be ignored and
untracked (spec: public-config-doctor)."""

from __future__ import annotations

from pathlib import Path

from tests.cli.public_content_repo import planning, public_content, said
from tests.cli.test_doctor_local_ignored import IGNORED, put
from tests.factories import git

OVERLAY = "abk.local.yaml"


def test_an_overlay_without_an_ignore_line_warns_naming_the_file_and_the_line_to_add(
    tmp_path: Path,
) -> None:
    config = planning(tmp_path / "plan", ignore=IGNORED)
    put(config.parent, OVERLAY)

    found = public_content(config)

    assert [c.status for c in found] == ["warn"]
    assert OVERLAY in said(found[0])
    assert OVERLAY in found[0].fix


def test_a_tracked_overlay_warns_that_it_is_tracked(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=f"{IGNORED}{OVERLAY}\n")
    put(config.parent, OVERLAY)
    git(config.parent, "add", "-f", OVERLAY)
    git(config.parent, "commit", "-qm", "the overlay")

    found = public_content(config)

    assert [c.status for c in found] == ["warn"]
    assert "tracked" in said(found[0])
    assert OVERLAY in said(found[0])


def test_an_ignored_untracked_overlay_gives_ok(tmp_path: Path) -> None:
    config = planning(tmp_path / "plan", ignore=f"{IGNORED}{OVERLAY}\n")
    put(config.parent, OVERLAY)

    assert [c.status for c in public_content(config)] == ["ok"]
