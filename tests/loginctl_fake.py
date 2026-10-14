"""A `loginctl` stand-in for the tests of the lingering check: it answers at the
protocol boundary, the text `loginctl show-user --property=Linger` prints."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any


class Loginctl:
    """A runner answering `loginctl` and accepting every other command.

    `state` is what `show-user` reports: `yes`, `no`, or None for a failure.
    `missing` makes `loginctl` raise as a machine without it would.
    """

    def __init__(
        self,
        state: str | None = "no",
        *,
        enable_ok: bool = False,
        missing: bool = False,
        calls: list[list[str]] | None = None,
    ) -> None:
        self.state = state
        self.enable_ok = enable_ok
        self.missing = missing
        self.calls: list[list[str]] = [] if calls is None else calls
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        if argv[0] != "loginctl":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if self.missing:
            raise FileNotFoundError("loginctl")
        if "show-user" in argv:
            if self.state is None:
                return subprocess.CompletedProcess(argv, 1, "", "no such user")
            return subprocess.CompletedProcess(argv, 0, f"Linger={self.state}\n", "")
        if "enable-linger" in argv:
            return subprocess.CompletedProcess(
                argv, 0 if self.enable_ok else 1, "", "" if self.enable_ok else "Access denied"
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    @property
    def asked(self) -> bool:
        return any(c[0] == "loginctl" and "show-user" in c for c in self.calls)

    @property
    def tried_enable(self) -> bool:
        return any(c[0] == "loginctl" and "enable-linger" in c for c in self.calls)

    @property
    def ran_sudo(self) -> bool:
        return any(c[0] == "sudo" for c in self.calls)


class SubprocessModule:
    """Stands in for the `subprocess` module `timers` reaches commands through."""

    def __init__(self, runner: Callable[..., Any]) -> None:
        self.run = runner

    def __getattr__(self, name: str):
        return getattr(subprocess, name)
