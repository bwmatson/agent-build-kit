"""A known-agent row claims a forbidden command's spelling is covered only on a live check."""

from __future__ import annotations

from agent_build_kit.runtimes import known_agents


def test_a_row_says_a_spelling_is_covered_only_when_its_note_records_a_live_check() -> None:
    for agent in known_agents.KNOWN_AGENTS:
        note = agent.spellings.strip()
        assert note, agent.name
        assert note.startswith("UNVERIFIED") or (
            "live check" in note.lower() and "covered" in note.lower()
        ), agent.name
