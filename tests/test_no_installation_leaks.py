"""This repo is a framework and never names an installation.

A structural check, deliberately term-free: the words that would identify an
installation must not appear here even as a deny list. What it looks for is
the *shape* of a leak — a home-directory path, a GitHub slug that is not a
fixture's, an issue-number anecdote, a product's config path, an environment
variable read by literal name outside the settings layer. The term-based half
of the check is `abk scrub-check`, run from an installation with the terms
derived from its own abk.yaml.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("src", "tests", "docs")
TEXT = {".py", ".md", ".yaml", ".yml", ".toml", ".service", ".timer", ".tmpl", ".txt", ".json"}
# Fixture owners, and the placeholder words a regex's own documentation uses.
FIXTURE_OWNERS = ("example", "acme", "octo", "owner", "o")
# Upstream projects the framework builds on and credits; not installations.
UPSTREAM_OWNERS = ("fission-ai",)
# Azure DevOps organisations a fixture may use.
FIXTURE_AZURE_ORGS = ("acme", "example", "o", "org")

# A product's config directory under the home directory; the agent runtime's
# own, and the XDG/ssh conventions, are the framework's business.
HOME_PRODUCT_DIR = re.compile(
    r'Path\.home\(\)\s*/\s*"\.(?!claude\b|local\b|config\b|cache\b|ssh\b)'
)
HOME_PATH = re.compile(r"(?<![\w/])~/(?!\.(?:claude|local|config|cache|ssh|volta)\b)|/home/[a-z]")
GITHUB_SLUG = re.compile(r"github\.com[:/](?P<owner>[A-Za-z0-9-]+)/[A-Za-z0-9._-]+")
AZURE_ORG = re.compile(r"dev\.azure\.com[:/](?:v3/)?(?!v3/)(?P<org>[A-Za-z0-9._-]+)")
NOREPLY = re.compile(r"\d+\+[A-Za-z0-9-]+@users\.noreply\.github\.com")
ANECDOTE = re.compile(r"(?<![\w/.])[a-z][a-z0-9-]{2,}#\d{1,4}\b")
DATED_ANECDOTE = re.compile(
    r"\b(decided|confirmed|checked|verified|observed|happened|since)\b[^\n]{0,30}\b20\d\d-\d\d-\d\d"
)
ENV_LITERAL = re.compile(r'os\.environ(?:\.get)?\(?\[?\s*"[A-Z_]+"')
ENV_ALLOWED = {"settings.py", "usage_guard.py", "config.py"}


def _files() -> list[Path]:
    found = []
    for top in SCANNED:
        for path in (ROOT / top).rglob("*"):
            if path.is_file() and path.suffix in TEXT and ".venv" not in path.parts:
                found.append(path)
    for name in ("README.md", "CLAUDE.md", "CHANGELOG.md"):
        if (ROOT / name).exists():
            found.append(ROOT / name)
    return found


def _hits(pattern: re.Pattern, *, skip: Collection[str] = ()) -> list[str]:
    hits = []
    for path in _files():
        if path.name in skip or path == Path(__file__):
            continue
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:100]}")
    return hits


def test_no_home_directory_product_paths() -> None:
    assert _hits(HOME_PRODUCT_DIR) == []


def test_no_home_paths_in_text() -> None:
    assert _hits(HOME_PATH) == []


def test_every_github_slug_belongs_to_a_fixture_owner() -> None:
    offending = []
    for path in _files():
        if path == Path(__file__):
            continue
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            for match in GITHUB_SLUG.finditer(line):
                if (
                    match["owner"] not in FIXTURE_OWNERS
                    and match["owner"].lower() not in UPSTREAM_OWNERS
                ):
                    offending.append(f"{path.relative_to(ROOT)}:{number}: {match.group(0)}")
    assert offending == []


def _foreign_azure_orgs(text: str) -> list[str]:
    return [
        match["org"] for match in AZURE_ORG.finditer(text) if match["org"] not in FIXTURE_AZURE_ORGS
    ]


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
    assert _foreign_azure_orgs(text) == caught


def test_every_azure_organisation_belongs_to_a_fixture() -> None:
    offending = []
    for path in _files():
        if path == Path(__file__):
            continue
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            if _foreign_azure_orgs(line):
                offending.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:100]}")
    assert offending == []


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
