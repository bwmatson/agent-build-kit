"""`scrub_text` replaces terms whole, longest first, and is idempotent."""

import argparse
from pathlib import Path

from agent_build_kit.cli.scrub import cmd_scrub_check
from agent_build_kit.scrub_terms import scrub_text, terms_for
from tests.conftest import make_installation


def test_the_longer_term_is_replaced_before_the_shorter_one() -> None:
    out = scrub_text("see app-service and app", ["app", "app-service"])

    assert out == "see <redacted> and <redacted>"


def test_the_match_is_case_insensitive() -> None:
    assert scrub_text("Runs On Example-Host", ["example-host"]) == "Runs On <redacted>"


def test_text_without_a_term_is_unchanged() -> None:
    assert scrub_text("nothing to see\n", ["svc-x"]) == "nothing to see\n"


def test_a_replacement_may_be_chosen() -> None:
    assert scrub_text("a svc-x b", ["svc-x"], replacement="<x>") == "a <x> b"


def test_scrubbing_its_own_output_changes_nothing() -> None:
    terms = ["app", "app-service", "svc-x"]
    once = scrub_text("App-Service, app and svc-x\n", terms)

    assert scrub_text(once, terms) == once


def test_a_term_inside_the_replacement_does_not_break_idempotence() -> None:
    once = scrub_text("an act of act", ["act"])

    assert once == "an <redacted> of <redacted>"
    assert scrub_text(once, ["act"]) == once


def test_show_terms_prints_what_terms_for_returns(tmp_path: Path, capsys) -> None:
    inst = make_installation(tmp_path / "planning")
    target = tmp_path / "checkout"
    target.mkdir()

    cmd_scrub_check(argparse.Namespace(target=str(target), show_terms=True), inst)

    expected = "terms: " + ", ".join(terms_for(inst, target=target))
    assert capsys.readouterr().out.splitlines()[0] == expected
