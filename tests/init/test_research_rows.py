"""Init's research of a language is in the ledger: one `init_research` row per call, with no unit,
change or repo (spec: usage-accounting, every agent call writes exactly one row)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from agent_build_kit.init.research import research
from agent_build_kit.installation import Installation
from tests.call_rows import Spending, agent_rows

BODY = "## Formatting\n\n- rule\n\n## Sources\n\n- https://example.invalid\n"


def test_a_research_call_writes_one_init_research_row(
    tmp_path: Path, workspace: Installation
) -> None:
    research(
        "python",
        built_in="seed",
        output=tmp_path / "python.md",
        runtime=Spending(answer=BODY),
        today=date(2030, 1, 2),
    )

    (row,) = agent_rows(workspace)
    assert (row["node"], row["unit"], row["change"], row["repo"], row["role"]) == (
        "init_research",
        "",
        "",
        "",
        "generic",
    )
    assert row["input_tokens"] == 1200
    assert row["outcome"] == "ok"
