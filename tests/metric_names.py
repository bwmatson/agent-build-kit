"""The metric names the package's source emits, found by scanning it: a direct
`telemetry.<kind>("abk...")` call or the helper's `emit_metric("<kind>", "abk...")`."""

from __future__ import annotations

import re
from pathlib import Path

import agent_build_kit

EMIT_CALL = re.compile(
    r"(?:telemetry\.(?:duration|observe|count|level)\(\s*"
    r"|emit_metric\(\s*[\"'](?:duration|observe|count|level)[\"'],\s*)"
    r"[\"'](abk\.[a-z0-9_.]+)[\"']"
)


def emitted_names() -> set[str]:
    names: set[str] = set()
    stack = [Path(root) for root in agent_build_kit.__path__]
    while stack:
        for entry in stack.pop().iterdir():
            if entry.is_dir():
                stack.append(entry)
            elif entry.name.endswith(".py"):
                names.update(EMIT_CALL.findall(entry.read_text()))
    return names
