"""The structural leak scan and `abk.local.yaml`: the file must be ignored and untracked, and
its text is read only when it is not (spec: public-leak-test)."""

from __future__ import annotations

from pathlib import Path

from tests.factories import git, init_repo
from tests.installation_leaks import leaks, overlay_leaks

OVERLAY = "abk.local.yaml"
LEAKY = (
    "verify:\n  env:\n    HOME_DIR: /home/someone/work\nrepos:\n  other:\n    path: ../sibling-x\n"
)


def repository(root: Path, *, ignore: str = "") -> Path:
    init_repo(root)
    (root / ".gitignore").write_text(ignore)
    git(root, "add", ".gitignore")
    git(root, "commit", "-qm", "base")
    return root


def put_overlay(root: Path, text: str = LEAKY) -> None:
    (root / OVERLAY).write_text(text)


def test_a_committed_overlay_is_reported_tracked_with_its_leaks_by_file_and_line(
    tmp_path: Path,
) -> None:
    root = repository(tmp_path / "plan")
    put_overlay(root)
    git(root, "add", OVERLAY)
    git(root, "commit", "-qm", "overlay")

    found = overlay_leaks(root)

    assert any(OVERLAY in line and "tracked" in line for line in found)
    assert any(line.startswith(f"{OVERLAY}:3:") for line in found)
    assert any(
        OVERLAY in line and "repos.other.path" in line and "sibling-x" not in line for line in found
    )


def test_an_untracked_unignored_overlay_is_reported_not_ignored(tmp_path: Path) -> None:
    root = repository(tmp_path / "plan")
    put_overlay(root, "verify:\n  env: {}\n")

    found = overlay_leaks(root)

    assert any(OVERLAY in line and "not ignored" in line for line in found)
    assert not any("tracked" in line and "not ignored" not in line for line in found)


def test_an_ignored_untracked_overlay_with_the_same_content_reports_nothing(
    tmp_path: Path,
) -> None:
    root = repository(tmp_path / "plan", ignore=f"{OVERLAY}\n")
    put_overlay(root)

    assert overlay_leaks(root) == []


def test_a_missing_overlay_reports_nothing(tmp_path: Path) -> None:
    assert overlay_leaks(repository(tmp_path / "plan")) == []


def test_a_directory_that_is_not_a_repository_counts_the_overlay_as_not_ignored(
    tmp_path: Path,
) -> None:
    (tmp_path / "plain").mkdir()
    put_overlay(tmp_path / "plain", "verify:\n  env: {}\n")

    found = overlay_leaks(tmp_path / "plain")

    assert any(OVERLAY in line and "not ignored" in line for line in found)


def test_the_committed_config_is_scanned_as_before(tmp_path: Path) -> None:
    root = repository(tmp_path / "plan", ignore=f"{OVERLAY}\n")
    (root / "abk.yaml").write_text("repos:\n  app:\n    path: .\n    note: /home/someone/x\n")
    put_overlay(root)

    assert [line.split(":")[0:2] for line in leaks(root)] == [["abk.yaml", "4"]]
    assert overlay_leaks(root) == []
