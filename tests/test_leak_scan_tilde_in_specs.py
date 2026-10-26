"""In the specification folder a tilde-relative path is not a home path (spec: public-leak-test)."""

from __future__ import annotations

from pathlib import Path

from tests.installation_leaks import home_path_leaks, leaks


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


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
