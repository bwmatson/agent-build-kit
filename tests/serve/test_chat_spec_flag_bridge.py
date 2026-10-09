"""The bridge turns the agent's spec-conflict flag, a fenced block in its reply, into a custom
event the page shows as a callout, whichever way the runtime delivers the words: a Claude
message whole, or an ACP agent's chunks.

    ```spec-conflict
    {"requirement": "<named>", "reason": "<why>"}
    ```

becomes `{"type": "CUSTOM", "name": "spec_conflict", "value": {"requirement", "reason"}}`.
The words stay in the message, so the history reads as it was said.
"""

from __future__ import annotations

import json
from typing import Any

from agent_build_kit.pipeline.transcript import TranscriptEvent
from agent_build_kit.serve.bridge import AgUiEncoder

REQUIREMENT = "The registry is written through its journal"
REASON = "The request writes the registry file directly."
BLOCK = f"```spec-conflict\n{json.dumps({'requirement': REQUIREMENT, 'reason': REASON})}\n```\n"


def encoded(*texts: str) -> list[dict[str, Any]]:
    encoder = AgUiEncoder()
    out = [
        made for text in texts for made in encoder.encode(TranscriptEvent(kind="text", text=text))
    ]
    return out + encoder.close()


def flags(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e["value"] for e in events if e["type"] == "CUSTOM" and e["name"] == "spec_conflict"]


def test_a_flag_in_a_reply_is_one_custom_event_naming_the_requirement() -> None:
    out = encoded(f"This contradicts the change.\n\n{BLOCK}")

    assert flags(out) == [{"requirement": REQUIREMENT, "reason": REASON}]
    said = "".join(e["delta"] for e in out if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "This contradicts the change." in said


def test_a_flag_that_arrives_in_chunks_is_one_event() -> None:
    cut = len(BLOCK) // 2

    out = encoded("This contradicts the change.\n\n", BLOCK[:cut], BLOCK[cut:])

    assert flags(out) == [{"requirement": REQUIREMENT, "reason": REASON}]
