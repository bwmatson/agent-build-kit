"""The structural leak scan (spec: public-leak-test).

It reads planning content (`openspec/`, the committed `abk.yaml` and the tracked unit store), and a
tilde-relative path in the specification folder is not a home path. It reads `abk.local.yaml` as
text only when that file is not ignored and untracked, and flags a repo path outside the checkout.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

from tests import installation_leaks
from tests.factories import git, init_repo
from tests.installation_leaks import (
    ANECDOTE,
    HOME_PRODUCT_DIR,
    NOREPLY,
    Scan,
    foreign_azure_orgs,
    foreign_slug_owners,
    hits,
    home_path_leaks,
    leaks,
    overlay_leaks,
    repo_path_leaks,
)

HOME_LINE = "see /home/someone/work for the checkout\n"
HOME_LINE_PATTERN = re.compile(r"/home/someone")


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_a_home_path_in_a_spec_fails_with_file_and_line(tmp_path: Path) -> None:
    write(tmp_path, "openspec/changes/feature/specs/x/spec.md", "# Spec\n\n" + HOME_LINE)

    found = leaks(tmp_path)

    assert len(found) == 1
    assert found[0].startswith("openspec/changes/feature/specs/x/spec.md:3:")


def test_a_non_fixture_slug_in_the_config_fails_with_file_and_line(tmp_path: Path) -> None:
    write(
        tmp_path,
        "abk.yaml",
        "repos:\n  app:\n    path: .\n    url: https://github.com/contoso/app\n",
    )

    found = leaks(tmp_path)

    assert len(found) == 1
    assert found[0].startswith("abk.yaml:4:")


def test_a_home_path_in_the_store_fails_with_file_and_line(tmp_path: Path) -> None:
    write(tmp_path, "runs/units.json", '{"units": [\n"/home/someone/work"\n]}\n')

    found = leaks(tmp_path)

    assert len(found) == 1
    assert found[0].startswith("runs/units.json:2:")


def test_a_home_path_in_a_run_log_under_the_state_directory_is_not_read(tmp_path: Path) -> None:
    write(tmp_path, "runs/unit-logs/feature-1.json", HOME_LINE)
    write(tmp_path, "runs/ledger.json", HOME_LINE)
    write(tmp_path, "runs/units.json", '{"units": []}\n')

    assert leaks(tmp_path) == []


def test_a_checkout_with_no_planning_content_passes(tmp_path: Path) -> None:
    write(tmp_path, "README.md", "A framework.\n")

    assert leaks(tmp_path) == []


@pytest.mark.parametrize("path", ["../sibling-x", "/srv/sibling-x", "~/sibling-x"])
def test_a_repo_path_outside_the_checkout_fails_naming_the_key_not_the_value(
    tmp_path: Path, path: str
) -> None:
    write(
        tmp_path,
        "abk.yaml",
        f"repos:\n  platform:\n    path: .\n  app:\n    path: {path}\n    slug: example/app\n",
    )

    found = repo_path_leaks(tmp_path)

    assert len(found) == 1
    assert "app" in found[0]
    assert "sibling-x" not in found[0]


@pytest.mark.parametrize("repos", ["repos:\n  app:\n", "repos: []\n", "repos:\n  app: .\n"])
def test_a_repos_entry_that_is_not_a_mapping_is_skipped(tmp_path: Path, repos: str) -> None:
    write(tmp_path, "abk.yaml", repos)

    assert repo_path_leaks(tmp_path) == []


@pytest.mark.parametrize("path", [".", "vendor/sub"])
def test_a_repo_path_inside_the_checkout_passes(tmp_path: Path, path: str) -> None:
    write(tmp_path, "abk.yaml", f"repos:\n  app:\n    path: {path}\n    slug: example/app\n")

    assert repo_path_leaks(tmp_path) == []


def test_a_tilde_path_in_a_spec_is_not_a_hit(tmp_path: Path) -> None:
    write(tmp_path, "openspec/specs/x/spec.md", "path: ~/work/app\n")

    assert home_path_leaks(tmp_path) == []


def test_an_absolute_home_path_in_a_spec_is_a_hit_with_path_and_line(tmp_path: Path) -> None:
    write(tmp_path, "openspec/specs/x/spec.md", "# Spec\n/home/someone/app\n")

    found = home_path_leaks(tmp_path)

    assert len(found) == 1
    assert found[0].startswith("openspec/specs/x/spec.md:2:")


def test_a_tilde_path_in_docs_is_a_hit(tmp_path: Path) -> None:
    write(tmp_path, "docs/x.md", "path: ~/work/app\n")

    assert len(home_path_leaks(tmp_path)) == 1


def test_the_whole_scan_follows_the_same_rule(tmp_path: Path) -> None:
    write(tmp_path, "openspec/specs/x/spec.md", "path: ~/work/app\n")
    write(tmp_path, "docs/x.md", "path: ~/work/app\n")

    found = leaks(tmp_path)

    assert len(found) == 1
    assert found[0].startswith("docs/x.md:1:")


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


def a_checkout(root: Path) -> Path:
    init_repo(root)
    for number in range(6):
        write(root, f"src/module_{number}.py", f"x = {number}\n")
    write(root, "docs/guide.md", HOME_LINE)
    write(root, "openspec/specs/x/spec.md", "path: ~/work/app\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "files")
    return root


def test_every_scan_of_one_scan_object_filters_what_was_read_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = a_checkout(tmp_path)
    reads: Counter[str] = Counter()
    real = installation_leaks.lines_of

    def counting(path: Path, errors: str = "strict") -> list[str]:
        reads[path.name] += 1
        return real(path, errors=errors)

    monkeypatch.setattr(installation_leaks, "lines_of", counting)
    scan = Scan(root)

    for found in (HOME_PRODUCT_DIR, NOREPLY, ANECDOTE, foreign_slug_owners, foreign_azure_orgs):
        scan.hits(found)
    scan.home_path_leaks()

    assert reads
    assert set(reads.values()) == {1}


def test_a_scan_object_gives_the_answers_of_the_standalone_scans(tmp_path: Path) -> None:
    root = a_checkout(tmp_path)
    scan = Scan(root)

    assert scan.hits(ANECDOTE) == hits(root, ANECDOTE)
    assert scan.hits(foreign_slug_owners) == hits(root, foreign_slug_owners)
    assert scan.home_path_leaks() == home_path_leaks(root)
    assert scan.home_path_leaks() == ["docs/guide.md:1: see /home/someone/work for the checkout"]


def test_a_scan_object_leaves_out_the_files_a_scan_skips(tmp_path: Path) -> None:
    root = a_checkout(tmp_path)

    assert Scan(root).hits(HOME_LINE_PATTERN, skip={"guide.md"}) == []
    assert len(Scan(root).hits(HOME_LINE_PATTERN)) == 1
