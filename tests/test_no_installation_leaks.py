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
    HOME_PATH,
    HOME_PRODUCT_DIR,
    NOREPLY,
    foreign_azure_orgs,
    foreign_slug_owners,
    hits,
    repo_path_leaks,
)

ROOT = Path(__file__).resolve().parents[1]


def _hits(pattern: re.Pattern, *, skip=()) -> list[str]:
    return hits(ROOT, pattern, skip=skip)


def test_no_home_directory_product_paths() -> None:
    assert _hits(HOME_PRODUCT_DIR) == []


def test_no_home_paths_in_text() -> None:
    assert _hits(HOME_PATH) == []


def test_every_github_slug_belongs_to_a_fixture_owner() -> None:
    assert hits(ROOT, foreign_slug_owners) == []


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


def test_every_azure_organisation_belongs_to_a_fixture() -> None:
    assert hits(ROOT, foreign_azure_orgs) == []


def test_no_personal_noreply_addresses() -> None:
    assert _hits(NOREPLY) == []


def test_no_issue_or_pr_number_anecdotes() -> None:
    assert _hits(ANECDOTE) == []


def test_no_dated_anecdotes() -> None:
    # A date beside "decided"/"confirmed"/... is a story about one
    # installation. CHANGELOG entries are dated on purpose.
    assert _hits(DATED_ANECDOTE, skip={"CHANGELOG.md"}) == []


@pytest.mark.parametrize("pattern", [ENV_LITERAL])
def test_environment_is_read_only_through_the_settings_layer(pattern: re.Pattern) -> None:
    hits = [h for h in _hits(pattern) if h.split(":")[0].rsplit("/", 1)[-1] not in ENV_ALLOWED]
    hits = [h for h in hits if not h.startswith("tests/")]
    assert hits == []


def test_a_tracked_config_names_no_path_outside_the_checkout() -> None:
    assert repo_path_leaks(ROOT) == []
