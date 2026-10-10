"""The `windows` provider: toasts raised through BurntToast from a Windows process."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

# The one command that installs the module; `abk init` offers it and `abk doctor` names it
# as the fix.
INSTALL_COMMAND = [
    "powershell.exe",
    "-NoProfile",
    "-Command",
    "Install-Module BurntToast -Scope CurrentUser",
]
# Lists the module when it is installed and prints nothing when it is not.
MODULE_CHECK_COMMAND = [
    "powershell.exe",
    "-NoProfile",
    "-Command",
    "Get-Module -ListAvailable BurntToast",
]


class WindowsNotifier:
    def __init__(
        self,
        *,
        run: Callable[..., subprocess.CompletedProcess] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._run = run
        self._timeout = timeout

    def show(self, id: str, title: str, body: str, link: str) -> None:
        raise NotImplementedError

    def clear(self, id: str) -> None:
        raise NotImplementedError
