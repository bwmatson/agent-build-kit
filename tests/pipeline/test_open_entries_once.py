"""The stack runner's answer finds the open entries of the earlier rounds once and both
lists their ids and renders them from that (spec: dry-cleanup, open entries derived once).

The review is weighed through the runner's own `weigh_review` with the reviewer's raw
JSON reply. The earlier round's finding is a dict that counts how often the entries'
`required` flag is read: that is what deciding whether an entry is open does, once per
computation of the open entries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit
from tests.pipeline.test_stack_runner import Recorder, make_runner


class Watched(dict):
    """A stored finding that counts the times its `required` flag is asked for."""

    required_reads = 0

    def get(self, key: Any, default: Any = None) -> Any:
        if key == "required":
            self.required_reads += 1
        return super().get(key, default)


def stored_finding(number: int) -> Watched:
    return Watched(
        id=f"1.{number}",
        file="src/pkg/units.py",
        line=182,
        summary=f"summary {number}",
        consequence="a unit builds without its dependency",
        done="iterate through_satisfied()",
        required=True,
        status="",
    )


def test_the_open_ids_and_the_rendered_note_come_from_one_pass_over_the_entries(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    runner = make_runner(store, Recorder(), tmp_path)
    findings = [stored_finding(1), stored_finding(2)]
    earlier = {"asked": "r", "response": "", "judged": "sha-1", "findings": findings}
    answered_open = [{"id": "1.1", "status": "open"}, {"id": "1.2", "status": "open"}]
    reply = json.dumps({"approved": True, "feedback": "", "earlier": answered_open})

    weighed = runner.weigh_review(unit(), reply, judged="sha-2", rounds=(earlier,))

    assert weighed.approved is False
    assert "Still open from earlier rounds:" in weighed.why
    assert "[1.1]" in weighed.why and "[1.2]" in weighed.why
    assert [f.required_reads for f in findings] == [1, 1]
