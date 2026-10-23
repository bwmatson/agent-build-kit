"""Only display, labels, cards and the history floor read a verdict (spec: review-triage).

A search of the package source finds the readers of the verdict file, the modules that open it
(`latest_verdict`, `review_tier`, `review_tiers`) or name it, only among the modules the spec
allows: the label, ordering, cards, review route, history floor, report and recording modules,
and the two that hand the file's path to them to describe what is shown (the pull request body
and `abk status`).
"""

from __future__ import annotations

import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "agent_build_kit"

READER = re.compile(r"\blatest_verdict\(|\breview_tiers?\(|verdicts\.json")

ALLOWED = {
    "pipeline/labels.py",  # the label
    "pipeline/review_order.py",  # the ordering
    "notify/cards.py",  # the cards
    "serve/server.py",  # the review route
    "pipeline/verdict.py",  # the history floor
    "cli/review_report.py",  # the report
    "pipeline/verdict_record.py",  # the recording
    "graph/nodes.py",  # the pull request body describes the tier
    "cli/pipeline.py",  # `abk status` shows the order
}


def test_the_verdict_file_is_read_only_by_the_modules_the_spec_names() -> None:
    readers = {
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*.py")
        if READER.search(path.read_text())
    }

    assert readers - ALLOWED == set()
    assert "notify/cards.py" in readers, "the cards follow the recorded tier"
