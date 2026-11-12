"""Test support: the commands and options a document shows, read against the `abk` parser."""

from __future__ import annotations

import argparse
import re

from agent_build_kit.cli import build_parser

OPTION = re.compile(r"(?<![\w-])--[a-z][a-z-]*")


def subcommand_parsers(group: str) -> dict[str, argparse.ArgumentParser]:
    """The parser of each subcommand of `abk <group>`, by name."""
    top = next(
        action
        for action in build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    found = next(
        action
        for action in top.choices[group]._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return dict(found.choices)


def command_texts(text: str, prefix: str) -> list[str]:
    """Each command the document shows: the line naming `prefix`, with the lines a trailing
    backslash continues."""
    lines = text.splitlines()
    found: list[str] = []
    for i, line in enumerate(lines):
        if prefix not in line:
            continue
        joined = line
        while joined.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            joined += " " + lines[i]
        found.append(joined)
    return found
