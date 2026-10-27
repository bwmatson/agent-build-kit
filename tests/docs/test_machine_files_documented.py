"""The documents and the changelog say the machine files stay untracked and `install-timers`
carries them into the pipeline worktree."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, runbook_step, squashed, unreleased_bullets

INIT = ROOT / "docs" / "init.md"
CONFIGURATION = ROOT / "docs" / "configuration.md"
RUNBOOK = ROOT / "docs" / "runbooks" / "move-agent-build-kit-planning.md"

UNTRACKED = r"untracked|not tracked|never committed|not committed|stay ignored|ignored by git"
CARRIES = r"install-timers.{0,120}(links|carries|linked|carried).{0,160}pipeline worktree"


def text_of(path) -> str:
    return squashed(path.read_text(encoding="utf-8"))


def test_each_document_says_the_files_stay_untracked_and_install_timers_carries_them() -> None:
    for path in (INIT, CONFIGURATION, RUNBOOK):
        text = text_of(path)
        assert "scrub.local" in text, path.name
        assert re.search(UNTRACKED, text), path.name
        assert re.search(CARRIES, text), path.name


def test_the_runbook_step_creates_the_files_before_install_timers() -> None:
    step = runbook_step(5)
    for name in ("abk.local.yaml", ".env", "scrub.local"):
        assert name in step
    assert re.search(r"(create|write).{0,200}install-timers", step)
    assert re.search(r"machine files", step)


def test_the_configuration_document_says_a_new_machine_creates_them_first() -> None:
    text = text_of(CONFIGURATION)
    assert re.search(r"(new|second) machine.{0,200}(creates|create).{0,120}working copy", text)
    assert re.search(r"abk doctor.{0,160}(fails|FAIL).{0,160}(missing|lacks)", text)


def test_the_changelog_has_an_entry_naming_install_timers_and_the_three_files() -> None:
    entries = [
        b
        for b in unreleased_bullets()
        if "install-timers" in b and all(n in b for n in (".env", "abk.local.yaml", "scrub.local"))
    ]
    assert len(entries) == 1
