"""The `command` provider: a template split into arguments, then filled, never run in a shell.

The process runner is faked at the `subprocess.run` boundary: what it is given is an argv
and keyword arguments, and what it returns is a completed process or a raised timeout.
"""

from __future__ import annotations

import subprocess

import pytest

from agent_build_kit.config import CommandTemplates
from agent_build_kit.notify.command import CommandNotifier
from agent_build_kit.notify.provider import ProviderError

AWKWARD = 'It\'s "ready"; now'


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


def notifier(show: str, clear: str = "", runner: Runner | None = None, **kw) -> CommandNotifier:
    return CommandNotifier(CommandTemplates(show=show, clear=clear), run=runner or Runner(), **kw)


def test_each_placeholder_is_filled_into_its_own_argument() -> None:
    runner = Runner()

    notifier("notify-send {title} {body} {link} {id}", runner=runner).show(
        "unit:review:feature/1", "Ready", "Review it", "https://example.test/pull/5"
    )

    ((argv, _),) = runner.calls
    assert argv == [
        "notify-send",
        "Ready",
        "Review it",
        "https://example.test/pull/5",
        "unit:review:feature/1",
    ]


def test_a_title_with_quotes_and_a_semicolon_is_one_argument_and_no_shell_runs() -> None:
    runner = Runner()

    notifier("notify-send {title} {body}", runner=runner).show("id", AWKWARD, "b", "l")

    ((argv, kwargs),) = runner.calls
    assert argv == ["notify-send", AWKWARD, "b"]
    assert not kwargs.get("shell")


def test_a_placeholder_inside_a_larger_argument_is_filled_in_place() -> None:
    runner = Runner()

    notifier("tool --title={title} --tag {id}", runner=runner).show("i", "T", "b", "l")

    assert runner.calls[0][0] == ["tool", "--title=T", "--tag", "i"]


def test_quoted_literals_in_the_template_are_split_before_filling() -> None:
    runner = Runner()

    notifier('tool --label "two words" {title}', runner=runner).show("i", "T", "b", "l")

    assert runner.calls[0][0] == ["tool", "--label", "two words", "T"]


def test_a_value_that_looks_like_a_placeholder_is_left_as_it_is() -> None:
    runner = Runner()

    notifier("tool {title} {link}", runner=runner).show("i", "{link}", "b", "https://x.test")

    assert runner.calls[0][0] == ["tool", "{link}", "https://x.test"]


def test_clear_fills_the_id_into_the_clear_template() -> None:
    runner = Runner()

    notifier("show {id}", "dismiss {id}", runner=runner).clear("unit:failed:feature/1")

    assert runner.calls[0][0] == ["dismiss", "unit:failed:feature/1"]


def test_an_empty_clear_template_runs_nothing() -> None:
    runner = Runner()

    notifier("show {id}", "", runner=runner).clear("unit:failed:feature/1")

    assert runner.calls == []


def test_a_non_zero_exit_is_a_provider_failure() -> None:
    with pytest.raises(ProviderError):
        notifier("show {id}", runner=Runner(returncode=3)).show("i", "t", "b", "l")


def test_a_non_zero_exit_from_clear_is_a_provider_failure() -> None:
    with pytest.raises(ProviderError):
        notifier("show {id}", "dismiss {id}", runner=Runner(returncode=1)).clear("i")


def test_a_timeout_is_a_provider_failure() -> None:
    runner = Runner(raises=subprocess.TimeoutExpired(["show"], 5))

    with pytest.raises(ProviderError):
        notifier("show {id}", runner=runner, timeout=5).show("i", "t", "b", "l")


def test_every_call_is_given_a_time_limit() -> None:
    runner = Runner()

    notifier("show {id}", runner=runner, timeout=7).show("i", "t", "b", "l")

    assert runner.calls[0][1]["timeout"] == 7


def test_a_program_that_is_not_installed_is_a_provider_failure() -> None:
    runner = Runner(raises=FileNotFoundError("show"))

    with pytest.raises(ProviderError):
        notifier("show {id}", runner=runner).show("i", "t", "b", "l")


def test_with_no_runner_given_the_command_runs_through_subprocess_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Runner()
    monkeypatch.setattr(subprocess, "run", runner)

    CommandNotifier(CommandTemplates(show="show {id}")).show("i", "t", "b", "l")

    assert runner.calls[0][0] == ["show", "i"]
