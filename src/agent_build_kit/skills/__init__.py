"""The skills the framework ships, and installing them into a repo.

Each `skills/<name>/SKILL.md` is written for the planning repo and the code
repos of an installation, so an agent working in any of them knows how to
read the pipeline, write a change, and change the config. Installing stamps
the framework version into the `generatedBy` header, which is how `abk
doctor` tells a stale copy from a current one — and how the installer tells
its own file from one somebody wrote by hand, which it never overwrites.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit import __version__
from agent_build_kit.model import Frozen

SKILLS_DIR = Path(__file__).parent
GENERATED_BY = "agent-build-kit"

_GENERATED_LINE = re.compile(
    rf"^generatedBy:\s*{re.escape(GENERATED_BY)}(?:\s+(?P<version>[0-9][0-9.]*))?\s*$", re.M
)


class InstalledSkill(Frozen):
    name: str
    path: Path
    # The framework version stamped at install; "" when the header has none.
    version: str
    # Whether the framework wrote it (a hand-written skill under the same
    # name is left alone).
    ours: bool


def names() -> list[str]:
    return sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))


def source(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text()


def rendered(name: str) -> str:
    """The skill with the framework version stamped into `generatedBy`."""
    return _GENERATED_LINE.sub(f"generatedBy: {GENERATED_BY} {__version__}", source(name), count=1)


def inspect(path: Path) -> InstalledSkill:
    match = _GENERATED_LINE.search(path.read_text()) if path.is_file() else None
    return InstalledSkill(
        name=path.parent.name,
        path=path,
        version=(match.group("version") or "") if match else "",
        ours=match is not None,
    )


def install(target: Path) -> tuple[list[Path], list[Path]]:
    """Copy every skill into `target/<name>/SKILL.md`.

    Returns (written, refused): a file whose `generatedBy` header is ours is
    overwritten, one that exists without it is refused and left as it is.
    """
    written: list[Path] = []
    refused: list[Path] = []
    for name in names():
        destination = target / name / "SKILL.md"
        if destination.exists() and not inspect(destination).ours:
            refused.append(destination)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered(name))
        written.append(destination)
    return written, refused


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def stale(target: Path) -> list[InstalledSkill]:
    """The framework's skills under `target` that are older than this
    release, or carry no version at all."""
    found = [inspect(target / name / "SKILL.md") for name in names()]
    return [
        skill
        for skill in found
        if skill.ours and _version_key(skill.version) < _version_key(__version__)
    ]
