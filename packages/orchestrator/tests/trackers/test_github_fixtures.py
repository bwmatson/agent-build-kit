"""Recorded GitHub bodies say where they came from; a body that does not is refused."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.trackers.ado_recorded import FixtureHeaderMissing, load
from tests.trackers.github_issue_host import RECORDED_GITHUB

# The bodies the issue tests rely on, each written from the GitHub documentation.
BODIES = (
    "issue",
    "issue_created",
    "sub_issues",
    "sub_issue_refused",
    "issue_types",
    "organization",
    "user",
    "authenticated_user",
    "issue_event_assigned",
    "issue_last_edit",
    "label",
)


@pytest.mark.integration
def test_the_reference_bodies_are_the_ones_the_tests_rely_on() -> None:
    assert sorted(path.stem for path in RECORDED_GITHUB.glob("*.json")) == sorted(BODIES)


@pytest.mark.parametrize("name", BODIES)
def test_each_recorded_body_names_its_source_page_and_date(name: str) -> None:
    recorded = load(name, RECORDED_GITHUB)

    assert recorded.source in {"reference", "live"}
    assert recorded.page.startswith("https://docs.github.com/")
    assert recorded.date
    assert recorded.body


@pytest.mark.parametrize("name", BODIES)
def test_a_body_without_a_header_is_rejected(name: str, tmp_path: Path) -> None:
    copy = tmp_path / "github"
    shutil.copytree(RECORDED_GITHUB, copy)
    document = json.loads((copy / f"{name}.json").read_text())
    (copy / f"{name}.json").write_text(json.dumps(document["body"]))

    with pytest.raises(FixtureHeaderMissing):
        load(name, copy)
