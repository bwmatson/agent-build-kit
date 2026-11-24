"""The `windows` provider: toasts raised through BurntToast from a Windows process."""

from __future__ import annotations

import base64
import subprocess
from collections.abc import Callable

from agent_build_kit.notify.provider import ProviderError

# The module release whose cmdlets the scripts below call; the cmdlet names and parameters
# changed between releases, so the install, the import and `abk doctor` all pin it.
BURNTTOAST_VERSION = "0.8.5"
# The one command that installs the module; `abk init` offers it and `abk doctor` names it
# as the fix. `-Force` keeps it from stopping at the NuGet and untrusted-repository prompts.
INSTALL_COMMAND = [
    "powershell.exe",
    "-NoProfile",
    "-Command",
    f"Install-Module BurntToast -RequiredVersion {BURNTTOAST_VERSION} -Scope CurrentUser -Force",
]
# Lists the module when it is installed and prints nothing when it is not.
MODULE_CHECK_COMMAND = [
    "powershell.exe",
    "-NoProfile",
    "-Command",
    "Get-Module -ListAvailable BurntToast",
]


_IMPORT = f"Import-Module BurntToast -RequiredVersion {BURNTTOAST_VERSION};"


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
            f"{_IMPORT} "
            f"New-BurntToastNotification -Text {_literal(title)}, {_literal(body)} "
            f"-UniqueIdentifier {_literal(id)}"
        )
        if link:
            script += f" -Button (New-BTButton -Content 'Open' -Arguments {_literal(link)})"
        self._execute(script)

    def clear(self, id: str) -> None:
        self._execute(f"{_IMPORT} Remove-BTNotification -Tag {_literal(id)}")

    def _execute(self, script: str) -> None:
        # The script travels as base64 UTF-16LE, so the Windows command line never re-parses
        # its quotes, backticks or non-ASCII text.
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        argv = ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded]
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
