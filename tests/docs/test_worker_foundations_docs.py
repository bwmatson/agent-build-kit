"""The architecture document names the worker foundations; the worker design marks step 1 done."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed

DOCS = ROOT / "docs"


def architecture() -> str:
    return squashed((DOCS / "architecture.md").read_text(encoding="utf-8"))


def test_the_architecture_document_names_the_identity_of_a_branch_lock() -> None:
    assert re.search(
        r"branch lock.{0,300}(pid.{0,80}start time|start time.{0,80}pid)"
        r"|(pid.{0,80}start time|start time.{0,80}pid).{0,300}branch lock",
        architecture(),
        re.I,
    )


def test_the_architecture_document_names_the_admission_lock() -> None:
    text = architecture()
    assert re.search(r"admission lock.{0,400}starting", text, re.I) or re.search(
        r"starting.{0,400}admission lock", text, re.I
    )


def test_the_architecture_document_names_the_snapshot_api() -> None:
    text = architecture()
    assert re.search(r"snapshot API", text, re.I)
    assert "request_refresh" in text
    assert re.search(r"snapshot API.{0,600}\bage\b|\bage\b.{0,600}snapshot API", text, re.I)


def test_the_worker_design_marks_migration_step_one_as_done() -> None:
    text = (DOCS / "designs" / "worker-design.md").read_text(encoding="utf-8")
    migration = text[text.index("\n## Migration") :]
    step = re.search(r"^1\. .*?(?=^2\. )", migration, re.M | re.S)
    assert step, "migration step 1 not found"
    heading = squashed(step.group(0)).split("Branch-lock", 1)[0]
    assert re.search(r"\bdone\b", heading, re.I)
