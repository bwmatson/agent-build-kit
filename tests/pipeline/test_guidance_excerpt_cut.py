"""What a history entry says of a person's note is cut by the shared head cut."""

from __future__ import annotations

from agent_build_kit.pipeline.unit_store import guidance_excerpt


def test_a_note_cut_inside_a_code_fence_closes_it() -> None:
    quoted = guidance_excerpt("```\n" + "x" * 300)

    assert len(quoted.removeprefix(" — ")) <= 200
    assert quoted.rstrip().endswith("```"), "the fence the cut left open is closed"
