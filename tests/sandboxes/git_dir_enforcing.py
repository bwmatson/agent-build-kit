"""A stand-in for a backend that enforces a policy's lists the way Landlock does: a rule on a
folder covers what is beneath it, now and later, and a rule on a file covers that file itself,
so it stops covering the name once another file is renamed over it."""

from __future__ import annotations

import os
from pathlib import Path

from agent_build_kit.sandboxes import SandboxPolicy


def replace_as_git_does(path: Path) -> None:
    """Replace `path` by writing `<name>.lock` and renaming it over the original."""
    lock = path.with_name(path.name + ".lock")
    lock.write_text(path.read_text())
    os.replace(lock, path)


class Enforcing:
    """What a process confined by `policy` may read and execute, decided when it starts."""

    def __init__(self, policy: SandboxPolicy) -> None:
        self.files = {self.identity(p) for p in policy.read if p.is_file()}
        self.folders = [p for p in policy.read if p.is_dir()]
        self.no_execute = list(policy.no_execute)

    @staticmethod
    def identity(path: Path) -> tuple[int, int]:
        found = path.stat()
        return found.st_dev, found.st_ino

    def can_read(self, path: Path) -> bool:
        path = path.resolve()
        if not path.exists():
            return False
        if path.is_file() and self.identity(path) in self.files:
            return True
        return any(path.is_relative_to(folder) for folder in self.folders)

    def can_execute(self, path: Path) -> bool:
        path = path.resolve()
        return self.can_read(path) and not any(path.is_relative_to(n) for n in self.no_execute)
