"""Recorded Azure DevOps bodies say where they came from; a body that does not is refused."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.trackers.ado_recorded import FixtureHeaderMissing, load

# The bodies the work item tests rely on, each written from the REST reference.
BODIES = ("work_item", "work_item_created", "wiql_result", "connection_data")
HEADER = {
    "source": "reference",
    "page": "https://learn.microsoft.com/rest/api",
    "date": "2026-10-28",
}


def write(directory: Path, name: str, document: dict) -> None:
    (directory / f"{name}.json").write_text(json.dumps(document))


@pytest.mark.parametrize("name", BODIES)
def test_each_recorded_body_names_its_source_page_and_date(name: str) -> None:
    recorded = load(name)

    assert recorded.source in {"reference", "live"}
    assert recorded.page.startswith("https://")
    assert recorded.date
    assert recorded.body


def test_a_body_with_a_header_is_loaded(tmp_path: Path) -> None:
    write(tmp_path, "item", {"fixture": HEADER, "body": {"id": 7}})

    recorded = load("item", tmp_path)

    assert (recorded.source, recorded.page, recorded.date) == tuple(HEADER.values())
    assert recorded.body == {"id": 7}


def test_a_body_without_a_header_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "item", {"id": 7})

    with pytest.raises(FixtureHeaderMissing):
        load("item", tmp_path)


@pytest.mark.parametrize("missing", ["source", "page", "date"])
def test_a_header_lacking_a_part_is_rejected(tmp_path: Path, missing: str) -> None:
    header = {key: value for key, value in HEADER.items() if key != missing}
    write(tmp_path, "item", {"fixture": header, "body": {"id": 7}})

    with pytest.raises(FixtureHeaderMissing):
        load("item", tmp_path)
