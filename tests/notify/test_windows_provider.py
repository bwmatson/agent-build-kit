"""The `windows` provider: the `powershell.exe -NoProfile` command line it builds for a card.

The process runner is faked at the `subprocess.run` boundary, as for the `command` provider.
The cmdlet names are not pinned here: they are settled by the hand-run acceptance task.
"""

from __future__ import annotations

import base64
import subprocess

import pytest

from agent_build_kit.config import NotificationProvider, NotificationsConfig
from agent_build_kit.notify.build import build_notifier
from agent_build_kit.notify.provider import ProviderError
from agent_build_kit.notify.windows import BURNTTOAST_VERSION, WindowsNotifier

AWKWARD_TITLE = 'It\'s "ready" for $(review); `now`'
NON_ASCII_TITLE = "Prêt à relire ✓ 日本語"


class Runner:
    def __init__(self, returncode: int = 0, raises: BaseException | None = None) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self._returncode = returncode
        self._raises = raises

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append((list(argv), kwargs))
        if self._raises:
            raise self._raises
        return subprocess.CompletedProcess(argv, self._returncode, b"", b"boom")


def script_of(argv: list[str]) -> str:
    """The script powershell.exe runs: `-EncodedCommand` is base64 of its UTF-16LE text."""
    assert argv[:3] == ["powershell.exe", "-NoProfile", "-EncodedCommand"]
    return base64.b64decode(argv[-1]).decode("utf-16-le")


def literal(text: str) -> str:
    """`text` as a PowerShell single-quoted string, where only a quote needs doubling."""
    return "'" + text.replace("'", "''") + "'"


def test_show_runs_powershell_without_a_profile_with_no_shell() -> None:
    runner = Runner()

    WindowsNotifier(run=runner).show(
        "unit:review:feature/1", "Ready", "Review it", "https://x.test"
    )

    ((argv, kwargs),) = runner.calls
    assert argv[:3] == ["powershell.exe", "-NoProfile", "-EncodedCommand"]
    assert not kwargs.get("shell")


def test_show_carries_the_title_body_link_and_id_intact() -> None:
    runner = Runner()

    WindowsNotifier(run=runner).show(
        "unit:review:feature/1", "Ready for review", "Body with spaces", "https://x.test/pull/5"
    )

    ((argv, _),) = runner.calls
    script = script_of(argv)
    for value in (
        "Ready for review",
        "Body with spaces",
        "https://x.test/pull/5",
        "unit:review:feature/1",
    ):
        assert literal(value) in script


def test_quotes_and_shell_metacharacters_in_a_value_cannot_break_out_of_its_string() -> None:
    runner = Runner()

    WindowsNotifier(run=runner).show("id", AWKWARD_TITLE, "b", "https://x.test")

    ((argv, _),) = runner.calls
    assert literal(AWKWARD_TITLE) in script_of(argv)


def test_a_non_ascii_title_reaches_powershell_intact() -> None:
    runner = Runner()

    WindowsNotifier(run=runner).show("id", NON_ASCII_TITLE, "b", "https://x.test")

    ((argv, _),) = runner.calls
    assert literal(NON_ASCII_TITLE) in script_of(argv)


def test_scripts_import_the_pinned_module_version_first() -> None:
    runner = Runner()
    notifier = WindowsNotifier(run=runner)

    notifier.show("id", "t", "b", "https://x.test")
    notifier.clear("id")

    import_line = f"Import-Module BurntToast -RequiredVersion {BURNTTOAST_VERSION};"
    for argv, _ in runner.calls:
        assert script_of(argv).startswith(import_line)


def test_a_card_without_a_link_has_no_button() -> None:
    runner = Runner()

    WindowsNotifier(run=runner).show("id", "t", "b", "")

    ((argv, _),) = runner.calls
    assert "New-BTButton" not in script_of(argv)


def test_clear_names_the_id_and_nothing_of_the_card() -> None:
    runner = Runner()

    WindowsNotifier(run=runner).clear("unit:review:feature/1")

    ((argv, _),) = runner.calls
    assert literal("unit:review:feature/1") in script_of(argv)


def test_clear_quotes_an_id_that_holds_a_quote() -> None:
    runner = Runner()

    WindowsNotifier(run=runner).clear("it's")

    ((argv, _),) = runner.calls
    assert literal("it's") in script_of(argv)


@pytest.mark.parametrize("call", ["show", "clear"])
def test_a_non_zero_exit_is_a_provider_failure(call: str) -> None:
    notifier = WindowsNotifier(run=Runner(returncode=1))

    with pytest.raises(ProviderError):
        if call == "show":
            notifier.show("id", "t", "b", "l")
        else:
            notifier.clear("id")


def test_a_timeout_is_a_provider_failure() -> None:
    runner = Runner(raises=subprocess.TimeoutExpired("powershell.exe", 30))

    with pytest.raises(ProviderError):
        WindowsNotifier(run=runner).show("id", "t", "b", "l")


def test_the_windows_provider_is_what_the_config_builds() -> None:
    config = NotificationsConfig(provider=NotificationProvider.WINDOWS)

    assert isinstance(build_notifier(config), WindowsNotifier)
