"""An environment whose `sync` and `check` are real child processes, so the
pipeline is driven through the argv it runs and nothing else.

Each command appends its name to a call log and reads switches from a control
folder: `check` fails while `broken` exists, and `sync` mends it while
`sync-repairs` exists. A test flips the switches the way a repaired or damaged
environment would change. A `sync` writes `lock-content` into every lock file the
environment names, in its working directory, the way a package manager's does.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from agent_build_kit.config import RepoConfig
from tests.conftest import workspace_config

BROKEN_OUTPUT = "ModuleNotFoundError: No module named 'widget'"
SYNC_FAILED_OUTPUT = "error: no solution found for widget>=9"

_CHECK = f"""\
import pathlib, sys

control = pathlib.Path(sys.argv[1])
with (control / "calls.log").open("a") as log:
    log.write("check" + chr(10))
if (control / "broken").exists():
    print({BROKEN_OUTPUT!r})
    sys.exit(1)
"""

_SYNC = f"""\
import pathlib, sys

control = pathlib.Path(sys.argv[1])
with (control / "calls.log").open("a") as log:
    log.write("sync" + chr(10))
if (control / "sync-fails").exists():
    print({SYNC_FAILED_OUTPUT!r})
    sys.exit(1)
if (control / "sync-repairs").exists():
    (control / "broken").unlink(missing_ok=True)
if (control / "lock-content").exists():
    runs = (control / "calls.log").read_text().split().count("sync")
    for name in sys.argv[2:]:
        pathlib.Path(name).write_text((control / "lock-content").read_text() + str(runs) + chr(10))
"""


class FakeEnvironment:
    """The state of one environment, and what has been run against it."""

    def __init__(
        self,
        control: Path,
        *,
        inputs: tuple[str, ...] = ("manifest.toml",),
        locks: tuple[str, ...] = (),
    ) -> None:
        control.mkdir(parents=True, exist_ok=True)
        self.control = control
        self.inputs = list(inputs)
        self.locks = list(locks)

    def config(self) -> dict[str, Any]:
        """The `environment` section, for `make_installation(..., environment=...)`."""
        return {
            "sync": [sys.executable, "-c", _SYNC, str(self.control), *self.locks],
            "check": [sys.executable, "-c", _CHECK, str(self.control)],
            "inputs": {"dependencies": self.inputs, "lock": self.locks},
        }

    def writes_lock(self, text: str) -> None:
        """From now on every `sync` writes `text` and the number of syncs run so far into each
        lock file, so that no two syncs leave the same lock, as a resolver's timestamps do."""
        (self.control / "lock-content").write_text(text)

    def calls(self) -> list[str]:
        log = self.control / "calls.log"
        return log.read_text().split() if log.exists() else []

    def note(self, name: str) -> None:
        """Put something else that happened into the call log, to order it among the commands."""
        with (self.control / "calls.log").open("a") as log:
            log.write(f"{name}\n")

    def clear(self) -> None:
        (self.control / "calls.log").unlink(missing_ok=True)

    def break_it(self, *, sync_repairs: bool = False) -> None:
        (self.control / "broken").write_text("")
        if sync_repairs:
            (self.control / "sync-repairs").write_text("")

    def fail_sync(self, *, failing: bool = True) -> None:
        if failing:
            (self.control / "sync-fails").write_text("")
        else:
            (self.control / "sync-fails").unlink(missing_ok=True)

    def mend(self) -> None:
        (self.control / "broken").unlink(missing_ok=True)


def repo_config(root: Path, env: FakeEnvironment | None = None, name: str = "app") -> RepoConfig:
    """The fixture workspace's repository `name`, with `env` as its environment section."""
    configured = workspace_config(root).repos[name].model_dump(mode="json")
    return RepoConfig.model_validate(configured | ({"environment": env.config()} if env else {}))
