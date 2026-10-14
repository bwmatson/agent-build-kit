"""Scanning a planning root's own checkout does not flag the root's name."""

import argparse
from pathlib import Path

from agent_build_kit.cli.scrub import cmd_scrub_check
from agent_build_kit.installation import Installation
from agent_build_kit.scrub_terms import terms_for
from tests.conftest import make_installation


def _inst(tmp_path: Path, *, with_platform: bool = False) -> tuple[Installation, Path]:
    root = tmp_path / "plan"
    repos = {"app": {"path": str(root), "slug": "example/app"}}
    if with_platform:
        repos["platform"] = {
            "path": str(tmp_path / "checkouts" / "plt"),
            "slug": "example/platform",
        }
    return make_installation(root, repos=repos), root


def _scan(inst: Installation, target: Path) -> int:
    return cmd_scrub_check(argparse.Namespace(target=str(target), show_terms=False), inst)


def test_the_root_s_name_is_not_a_term_on_its_own_checkout(tmp_path: Path, capsys) -> None:
    inst, root = _inst(tmp_path)
    (root / "notes.md").write_text("this is the plan\n")

    assert "plan" not in terms_for(inst, target=root)
    assert _scan(inst, root) == 0
    assert "clean" in capsys.readouterr().out


def test_the_root_s_name_is_a_term_on_another_checkout(tmp_path: Path, capsys) -> None:
    inst, _ = _inst(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "notes.md").write_text("this is the plan\n")

    assert "plan" in terms_for(inst, target=other)
    assert _scan(inst, other) == 1
    assert "notes.md:1: plan" in capsys.readouterr().out


def test_another_repo_s_name_is_still_a_term_on_the_root(tmp_path: Path, capsys) -> None:
    inst, root = _inst(tmp_path, with_platform=True)
    (root / "notes.md").write_text("see platform\n")

    assert "platform" in terms_for(inst, target=root)
    assert _scan(inst, root) == 1
    assert "notes.md:1: platform" in capsys.readouterr().out
