"""The planning repo's configuration files are a person's to change, and a run that changes one
fails.

The command policy refuses the routes it names to write them, but a command cannot be parsed for
every route (an interpreter one-liner, a copy tool). So the code that runs an agent also reads
both files before the run and again after it. The files are not restored: whoever changed them
meant to, or a person did while the run was in progress, and either way a person decides.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_build_kit.config import CONFIG_FILENAME, overlay_path


class ConfigChanged(RuntimeError):
    """A configuration file differs after a run from what it was before."""


def config_files(root: Path) -> tuple[Path, Path]:
    """The planning repo's `abk.yaml` and the local overlay beside it; either may be absent."""
    config = root / CONFIG_FILENAME
    return config, overlay_path(config)


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _difference(path: Path, before: bytes | None, after: bytes | None) -> str:
    def lines(content: bytes | None) -> list[str]:
        return [] if content is None else content.decode(errors="replace").splitlines(keepends=True)

    state = "was created" if before is None else "was deleted" if after is None else "differs"
    diff = "".join(
        difflib.unified_diff(
            lines(before), lines(after), fromfile=f"{path.name} before", tofile=f"{path.name} after"
        )
    )
    return f"{path.name} changed during the run ({state}):\n{diff}"


@contextmanager
def config_unchanged(root: Path) -> Iterator[None]:
    """Run the block, then raise `ConfigChanged` if `abk.yaml` or `abk.local.yaml` under `root`
    differs from what it was on entry, naming the file and showing the difference.

    A block that raised is compared too: a run that stops (the usage window, an interruption) is
    often resumed, and the resumed run would take the changed file as its own start. When a file
    differs, `ConfigChanged` replaces the error, chained from it, so the unit fails instead of
    being parked; when nothing differs, the block's error propagates unchanged."""
    watched = config_files(root)
    before = {path: _read(path) for path in watched}
    raised: BaseException | None = None
    try:
        yield
    except BaseException as error:
        raised = error
    problems = [
        _difference(path, before[path], after)
        for path in watched
        if (after := _read(path)) != before[path]
    ]
    if problems:
        raise ConfigChanged(
            "\n".join(problems)
            + "\nThe file is a person's to change and is left as it is now. If a person edited it "
            "while the run was in progress, requeue the unit once the edit is done."
        ) from raised
    if raised is not None:
        raise raised
