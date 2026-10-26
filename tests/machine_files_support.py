"""A working copy with a pipeline worktree and machine files to carry, built with real git."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.init.scaffold import template
from agent_build_kit.machine_files import MACHINE_FILES, Carried

# The packaged `.gitignore`, which ignores every machine file.
GITIGNORE = template("gitignore")

# The machine files, as `MACHINE_FILES` lists them.
ALL = MACHINE_FILES

CONTENT = {".env": "TOKEN=one\n", "abk.local.yaml": "planning: {}\n", "scrub.local": "secret\n"}


def give(working_copy: Path, *names: str) -> None:
    """Write these machine files into the working copy, each with its own content."""
    for name in names:
        (working_copy / name).write_text(CONTENT[name])


def results(carried: tuple[Carried, ...]) -> dict[str, str]:
    """What `carry` reported, name to result."""
    return {item.name: item.result for item in carried}
