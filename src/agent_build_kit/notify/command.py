"""The `command` provider: a configured argv template run for each card."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable

from agent_build_kit.config import CommandTemplates, fill_template
from agent_build_kit.notify.provider import ProviderError


class CommandNotifier:
    def __init__(
        self,
        templates: CommandTemplates,
        *,
        run: Callable[..., subprocess.CompletedProcess] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._templates = templates
        self._run = run
        self._timeout = timeout

    def show(self, id: str, title: str, body: str, link: str) -> None:
        self._execute(self._templates.show, id=id, title=title, body=body, link=link)

    def clear(self, id: str) -> None:
        self._execute(self._templates.clear, id=id)

    def _execute(self, template: str, **values: str) -> None:
        if not template:
            return
        # Split before filling, so a value is one argument whatever it holds.
        argv = [fill_template(part, values) for part in shlex.split(template)]
        run = self._run or subprocess.run
        try:
            done = run(argv, capture_output=True, timeout=self._timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProviderError(f"{argv[0]}: {error}") from error
        if done.returncode != 0:
            raise ProviderError(f"{argv[0]} exited {done.returncode}")
