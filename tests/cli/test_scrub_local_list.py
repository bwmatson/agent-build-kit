"""`scrub.local` in the planning root adds terms and, with `!`, removes derived ones."""

import argparse
from pathlib import Path

from agent_build_kit.cli.scrub import cmd_scrub_check
from agent_build_kit.installation import Installation
from agent_build_kit.scrub_terms import terms_for
from tests.conftest import make_installation


def _inst(tmp_path: Path) -> Installation:
    return make_installation(tmp_path / "planning")


def _local(tmp_path: Path, text: str) -> None:
    (tmp_path / "planning" / "scrub.local").write_text(text)


def test_the_list_adds_its_terms_and_skips_comments_and_blanks(tmp_path: Path) -> None:
    inst = _inst(tmp_path)
    before = set(terms_for(inst, target=tmp_path))
    _local(tmp_path, "example-host\n# a comment\n\nsvc-x # a host\n")

    assert set(terms_for(inst, target=tmp_path)) - before == {"example-host", "svc-x"}


def test_a_scan_matches_a_local_term_case_insensitively(tmp_path: Path, capsys) -> None:
    inst = _inst(tmp_path)
    _local(tmp_path, "example-host\n")
    target = tmp_path / "checkout"
    target.mkdir()
    (target / "a.md").write_text("runs on Example-Host\n")

    assert cmd_scrub_check(argparse.Namespace(target=str(target), show_terms=True), inst) == 1
    out = capsys.readouterr().out
    assert "a.md:1: Example-Host" in out
    assert "example-host" in out.splitlines()[0]


def test_a_generic_word_written_in_the_list_is_kept(tmp_path: Path) -> None:
    inst = _inst(tmp_path)
    _local(tmp_path, "docker\n")

    assert "docker" in terms_for(inst, target=tmp_path)


def test_a_bang_line_removes_a_derived_term(tmp_path: Path) -> None:
    inst = _inst(tmp_path)
    _local(tmp_path, "!platform\n")

    assert "platform" not in terms_for(inst, target=tmp_path)
    assert "app" in terms_for(inst, target=tmp_path)


def test_a_term_under_three_characters_is_dropped(tmp_path: Path) -> None:
    inst = _inst(tmp_path)
    _local(tmp_path, "ab\nabc\n")

    terms = terms_for(inst, target=tmp_path)
    assert "abc" in terms
    assert "ab" not in terms


def test_no_list_adds_nothing_and_fails_nothing(tmp_path: Path, capsys) -> None:
    inst = _inst(tmp_path)
    target = tmp_path / "checkout"
    target.mkdir()

    assert "platform" in terms_for(inst, target=target)
    assert cmd_scrub_check(argparse.Namespace(target=str(target), show_terms=False), inst) == 0
    assert "clean" in capsys.readouterr().out
