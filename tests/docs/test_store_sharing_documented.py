"""`docs/configuration.md` says state is shared between devices through the store's server."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def section(heading: str) -> str:
    """The body of the `### heading` section of the configuration document."""
    text = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    return text.split(f"### {heading}\n", 1)[1].split("\n### ", 1)[0]


def test_the_store_section_says_state_is_shared_through_the_server_not_a_network_drive() -> None:
    store = section("`store`")

    assert "`store.url`" in store
    assert "`abk db" in store
    assert "network drive" in store.lower()


def test_the_network_drive_section_keeps_its_content_and_points_to_the_store_url() -> None:
    drive = section("Network drive")

    assert "`store.url`" in drive
    assert "`units.json`" in drive
    assert "lock probe" in drive
