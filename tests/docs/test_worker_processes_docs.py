"""The documents describe worker processes: the `workers` settings, the wake path, the status and
doctor output, and the design document marks the steps the code has reached."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed, unreleased_bullets

DOCS = ROOT / "docs"


def document(name: str) -> str:
    return squashed((DOCS / name).read_text(encoding="utf-8"))


def test_the_architecture_document_describes_the_mode_and_the_wake_path() -> None:
    text = document("architecture.md")

    assert "workers.mode" in text
    assert re.search(r"processes.{0,200}dispatcher|dispatcher.{0,200}processes", text, re.I)
    assert "runs/wake" in text
    assert re.search(r"path unit", text, re.I)


def test_the_architecture_document_describes_the_limits() -> None:
    text = document("architecture.md")

    assert "workers.memory_max" in text
    assert "workers.cpu_weight" in text


def test_the_configuration_document_describes_each_workers_key() -> None:
    text = document("configuration.md")

    for key in ("workers.mode", "workers.memory_max", "workers.cpu_weight"):
        assert key in text
    assert re.search(r"threads.{0,200}default|default.{0,200}threads", text, re.I)
    assert "processes" in text


def test_the_configuration_document_says_where_the_wake_file_is_and_what_touches_it() -> None:
    text = document("configuration.md")

    assert "runs/wake" in text
    assert re.search(r"abk install-timers", text)


def test_the_design_document_marks_steps_two_and_three_done() -> None:
    text = (DOCS / "designs" / "worker-design.md").read_text(encoding="utf-8")

    for step, title in ((2, "The worker entry point and the spawner"), (3, "The dispatcher mode")):
        match = re.search(rf"^{step}\. \*\*{title}.*?\*\*", text, re.M)
        assert match, f"step {step} not found"
        assert "(done)" in match.group(0)
    later = re.search(r"^4\. \*\*.*?\*\*", text, re.M)
    assert later and "(done)" not in later.group(0)


def test_the_changelog_says_what_status_and_doctor_show() -> None:
    bullets = [b for b in unreleased_bullets() if "abk worker build" in b]

    assert len(bullets) == 1
    assert "abk status" in bullets[0]
    assert "abk doctor" in bullets[0]
