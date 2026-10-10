"""The `windows` provider: toasts raised through BurntToast from a Windows process."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from agent_build_kit.notify.provider import ProviderError

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
        script = (
            f"New-BurntToastNotification -Text {_literal(title)}, {_literal(body)} "
            f"-UniqueIdentifier {_literal(id)} "
            f"-Button (New-BTButton -Content 'Open' -Arguments {_literal(link)})"
        )
        self._execute(script)

    def clear(self, id: str) -> None:
        self._execute(f"Remove-BTNotification -Tag {_literal(id)}")

    def _execute(self, script: str) -> None:
        argv = ["powershell.exe", "-NoProfile", "-Command", script]
        run = self._run or subprocess.run
        try:
            done = run(argv, capture_output=True, timeout=self._timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProviderError(f"{argv[0]}: {error}") from error
        if done.returncode != 0:
            raise ProviderError(f"{argv[0]} exited {done.returncode}")


def _literal(text: str) -> str:
    """`text` as a PowerShell single-quoted string, where only a quote needs doubling."""
    return "'" + text.replace("'", "''") + "'"
