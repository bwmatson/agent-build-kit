"""The structural leak scan also reads planning content: `openspec/`, the committed
`abk.yaml` and the tracked unit store (spec: public-leak-test)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.installation_leaks import leaks, repo_path_leaks

HOME_LINE = "see /home/someone/work for the checkout\n"


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
    write(tmp_path, "runs/unit-logs/feature-1.log", HOME_LINE)
    write(tmp_path, "runs/decisions.jsonl", HOME_LINE)
    write(tmp_path, "abk.yaml", "repos:\n  app:\n    path: .\n    slug: example/app\n")

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


@pytest.mark.parametrize("path", [".", "vendor/sub"])
def test_a_repo_path_inside_the_checkout_passes(tmp_path: Path, path: str) -> None:
    write(tmp_path, "abk.yaml", f"repos:\n  app:\n    path: {path}\n    slug: example/app\n")

    assert repo_path_leaks(tmp_path) == []
