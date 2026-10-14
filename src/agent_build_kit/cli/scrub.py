"""`abk scrub-check`: the framework checkout must not name this installation.

The framework's own test (`tests/test_no_installation_leaks.py`) is
structural and term-free by design — the words that identify an installation
must not appear in the framework even as a deny list. This is the other half:
run *from* an installation, it derives the forbidden terms from the
installation's own `abk.yaml` — repo names, GitHub owners, checkout
directories, service names in deploy rules, credential and env variable
names, key file names — and greps a target checkout for them. The list
therefore lives nowhere; it is computed each time from what the installation
knows about itself.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.scrub_terms import scrub_text, terms_for

TEXT_SUFFIXES = {
    ".py", ".md", ".yaml", ".yml", ".toml", ".json", ".txt",
    ".service", ".timer", ".tmpl", ".cfg", ".ini", ".sh",
}  # fmt: skip
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}

__all__ = ["register", "scan", "scrub_text", "terms_for"]


def scan(target: Path, terms: list[str]) -> list[str]:
    """`path:line: term` for every occurrence, case-insensitive."""
    if not terms:
        return []
    pattern = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
    hits: list[str] = []
    for path in sorted(target.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts) or not path.is_file():
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in ("LICENSE", "Dockerfile"):
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            match = pattern.search(line)
            if match:
                hits.append(f"{path.relative_to(target)}:{number}: {match.group(0)}")
    return hits


def cmd_scrub_check(args: argparse.Namespace, inst: Installation) -> int:
    target = Path(args.target).expanduser().resolve()
    if not target.is_dir():
        print(f"abk scrub-check: {target} is not a directory")
        return 2
    terms = terms_for(inst, target=target)
    hits = scan(target, terms)
    if args.show_terms:
        print("terms:", ", ".join(terms))
    for hit in hits:
        print(hit)
    if hits:
        print(f"{len(hits)} reference(s) to this installation in {target}")
        return 1
    print(f"{target}: clean ({len(terms)} terms checked)")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "scrub-check",
        help="grep a checkout (the framework's) for anything that names this installation",
    )
    parser.add_argument("--target", required=True, help="the checkout to scan")
    parser.add_argument("--show-terms", action="store_true", help="print the derived term list")
    parser.set_defaults(func=cmd_scrub_check)
