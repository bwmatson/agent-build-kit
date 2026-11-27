"""`docs/configuration.md` says state is shared between devices through the store's server."""

from __future__ import annotations

from pathlib import Path

from tests.prompt_text import section

CONFIGURATION = Path(__file__).resolve().parents[2] / "docs" / "configuration.md"


def test_the_store_section_says_state_is_shared_through_the_server_not_a_network_drive() -> None:
    store = section(CONFIGURATION, "`store`")

    assert "`store.url`" in store
    assert "`abk db" in store
    assert "network drive" in store.lower()
    assert "`store.host` and `store.database`" in store


def test_the_network_drive_section_keeps_its_content_and_points_to_the_store_url() -> None:
    drive = section(CONFIGURATION, "Network drive")

    assert "`store.url`" in drive
    assert "`units.json`" in drive
    assert "lock probe" in drive
