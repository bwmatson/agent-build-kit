"""The structural leak scan, over a checkout's text and its committed planning content.

A structural check, deliberately term-free: the words that would identify an
installation must not appear here even as a deny list. What it looks for is
the *shape* of a leak — a home-directory path, a GitHub slug that is not a
fixture's, an issue-number anecdote, a product's config path, an environment
variable read by literal name outside the settings layer. The term-based half
of the check is `abk scrub-check`, run from an installation with the terms
derived from its own abk.yaml.

`tests/test_no_installation_leaks.py` runs it over this repository; tests of the scan
itself run it over a temporary tree.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Collection
from pathlib import Path

import yaml

from agent_build_kit.scrub_terms import TOOL_DIRS

SCANNED = ("src", "tests", "docs", "web", "openspec")
# The root files read when present; `abk.yaml` and the tracked unit store are planning
# content, read as committed. Ignored state (logs, ledgers) is not listed.
ROOT_FILES = ("README.md", "CLAUDE.md", "CHANGELOG.md", "abk.yaml", "runs/units.json")
# Installed and built files are not this repo's own text.
SKIPPED_PARTS = {".venv", "node_modules", "dist"}
TEXT = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".service",
    ".timer",
    ".tmpl",
    ".txt",
    ".json",
    ".ts",
    ".tsx",
    ".html",
    ".xml",
}
# The files that spell the patterns, or fixtures of what they catch, as text.
SELF = {
    "installation_leaks.py",
    "test_no_installation_leaks.py",
    "test_leak_scan_planning_content.py",
}
# Fixture owners, and the placeholder words a regex's own documentation uses.
FIXTURE_OWNERS = ("example", "acme", "octo", "owner", "o")
# Upstream projects the framework builds on and credits; not installations.
UPSTREAM_OWNERS = ("fission-ai", "astral-sh", "facebook", "adrienverge", "pre-commit")
# Azure DevOps organisations a fixture may use.
FIXTURE_AZURE_ORGS = ("acme", "example", "o", "org")

# A product's config directory under the home directory; the agent runtime's
# own, and the XDG/ssh conventions, are the framework's business.
# The tool directories are the framework's own list, shared with `abk scrub-check`.
_TOOL_DIR_NAMES = "|".join(re.escape(d.removeprefix(".")) for d in sorted(TOOL_DIRS))
HOME_PRODUCT_DIR = re.compile(rf'Path\.home\(\)\s*/\s*"\.(?!(?:{_TOOL_DIR_NAMES})\b)')
HOME_PATH = re.compile(rf"(?<![\w/])~/(?!\.(?:{_TOOL_DIR_NAMES})\b)|/home/[a-z]")
GITHUB_SLUG = re.compile(r"github\.com[:/](?P<owner>[A-Za-z0-9-]+)/[A-Za-z0-9._-]+")
AZURE_ORG = re.compile(r"dev\.azure\.com[:/](?:v3/)?(?!v3/)(?P<org>[A-Za-z0-9._-]+)")
NOREPLY = re.compile(r"\d+\+[A-Za-z0-9-]+@users\.noreply\.github\.com")
ANECDOTE = re.compile(r"(?<![\w/.])[a-z][a-z0-9-]{2,}#\d{1,4}\b")
DATED_ANECDOTE = re.compile(
    r"\b(decided|confirmed|checked|verified|observed|happened|since)\b[^\n]{0,30}\b20\d\d-\d\d-\d\d"
)
ENV_LITERAL = re.compile(r'os\.environ(?:\.get)?\(?\[?\s*"[A-Z_]+"')
ENV_ALLOWED = {"settings.py", "usage_guard.py", "config.py"}
SHAPES = (HOME_PRODUCT_DIR, HOME_PATH, NOREPLY, ANECDOTE)


def files(root: Path) -> list[Path]:
    built_ui = root / "src" / "agent_build_kit" / "serve" / "static"
    found = []
    for top in SCANNED:
        for path in (root / top).rglob("*"):
            if (
                path.is_file()
                and path.suffix in TEXT
                and not SKIPPED_PARTS.intersection(path.parts)
                and path.name != "package-lock.json"
                and built_ui not in path.parents
            ):
                found.append(path)
    found.extend(root / name for name in ROOT_FILES if (root / name).is_file())
    return [path for path in found if path.name not in SELF]


def hits(
    root: Path, found: re.Pattern | Callable[[str], object], *, skip: Collection[str] = ()
) -> list[str]:
    """Each line of the scanned files that a pattern matches or a predicate accepts, as
    `path:line: clipped line`."""
    matches = found.search if isinstance(found, re.Pattern) else found
    return [
        f"{path.relative_to(root)}:{number}: {line.strip()[:100]}"
        for path in files(root)
        if path.name not in skip
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1)
        if matches(line)
    ]


def foreign_azure_orgs(text: str) -> list[str]:
    return [
        match["org"] for match in AZURE_ORG.finditer(text) if match["org"] not in FIXTURE_AZURE_ORGS
    ]


def foreign_slug_owners(text: str) -> list[str]:
    return [
        match["owner"]
        for match in GITHUB_SLUG.finditer(text)
        if match["owner"] not in FIXTURE_OWNERS and match["owner"].lower() not in UPSTREAM_OWNERS
    ]


def leaks(root: Path) -> list[str]:
    """Each hit under `root` as `path:line: clipped line`: home paths, non-fixture slugs,
    anecdotes and product directories in the scanned text, planning content included."""
    return hits(
        root,
        lambda line: (
            any(shape.search(line) for shape in SHAPES)
            or foreign_slug_owners(line)
            or foreign_azure_orgs(line)
        ),
    )


def repo_path_leaks(root: Path) -> list[str]:
    """One finding per `repos.<name>.path` of `root`'s committed `abk.yaml` that leaves the
    checkout, naming the repo key and never the value."""
    config = root / "abk.yaml"
    if not config.is_file():
        return []
    loaded = yaml.safe_load(config.read_text())
    repos = loaded.get("repos") if isinstance(loaded, dict) else None
    base = Path(os.path.abspath(root))
    found = []
    for name, repo in (repos if isinstance(repos, dict) else {}).items():
        if not isinstance(repo, dict):
            continue
        path = str(repo.get("path", "."))
        target = Path(os.path.normpath(base / Path(path).expanduser()))
        if target != base and base not in target.parents:
            found.append(f"abk.yaml: repos.{name}.path leaves the checkout")
    return found
