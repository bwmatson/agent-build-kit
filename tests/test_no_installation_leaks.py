"""This repo is a framework and never names an installation.

The scan lives in `tests/installation_leaks.py`; this runs it over this checkout.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.installation_leaks import (
    ANECDOTE,
    DATED_ANECDOTE,
    ENV_ALLOWED,
    ENV_LITERAL,
    HOME_PRODUCT_DIR,
    NOREPLY,
    Scan,
    foreign_azure_orgs,
    foreign_slug_owners,
    overlay_leaks,
    repo_path_leaks,
)
from tests.time_limit import LOADED_TEST_TIME_LIMIT

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def scan() -> Scan:
    """The files the scans read, listed and read once for every scan of the gate."""
    return Scan(ROOT)


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_no_home_directory_product_paths(scan: Scan) -> None:
    assert scan.hits(HOME_PRODUCT_DIR) == []


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_no_home_paths_in_text(scan: Scan) -> None:
    assert scan.home_path_leaks() == []


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_every_github_slug_belongs_to_a_fixture_owner(scan: Scan) -> None:
    assert scan.hits(foreign_slug_owners) == []


@pytest.mark.parametrize(
    ("text", "caught"),
    [
        ("https://dev.azure.com/contoso-real/Project/_git/Repo", ["contoso-real"]),
        ("https://dev.azure.com/example/Project/_git/Repo", []),
        ("git@ssh.dev.azure.com:v3/contoso-real/Project/Repo", ["contoso-real"]),
        ("git@ssh.dev.azure.com:v3/acme/Project/Repo", []),
        ("https://acme@dev.azure.com/contoso-real/Project", ["contoso-real"]),
    ],
)
def test_the_azure_organisation_rule_sees_a_foreign_organisation(
    text: str, caught: list[str]
) -> None:
    assert foreign_azure_orgs(text) == caught


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_every_azure_organisation_belongs_to_a_fixture(scan: Scan) -> None:
    assert scan.hits(foreign_azure_orgs) == []


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_no_personal_noreply_addresses(scan: Scan) -> None:
    assert scan.hits(NOREPLY) == []


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_no_issue_or_pr_number_anecdotes(scan: Scan) -> None:
    assert scan.hits(ANECDOTE) == []


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_no_dated_anecdotes(scan: Scan) -> None:
    # A date beside "decided"/"confirmed"/... is a story about one
    # installation. CHANGELOG entries are dated on purpose, and so are the
    # reports a track writes under docs/reports/: each one is a dated record.
    found = scan.hits(DATED_ANECDOTE, skip={"CHANGELOG.md"})
    assert [hit for hit in found if not hit.startswith("docs/reports/")] == []


@pytest.mark.parametrize("pattern", [ENV_LITERAL])
@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_environment_is_read_only_through_the_settings_layer(
    scan: Scan, pattern: re.Pattern
) -> None:
    hits = [h for h in scan.hits(pattern) if h.split(":")[0].rsplit("/", 1)[-1] not in ENV_ALLOWED]
    hits = [h for h in hits if not h.startswith("tests/")]
    assert hits == []


@pytest.mark.integration
def test_a_tracked_config_names_no_path_outside_the_checkout() -> None:
    assert repo_path_leaks(ROOT) == []


def test_this_checkout_holds_no_tracked_or_unignored_overlay() -> None:
    assert overlay_leaks(ROOT) == []
