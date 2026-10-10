"""The `command` provider: a configured argv template run for each card."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from agent_build_kit.config import CommandTemplates


class CommandNotifier:
    def __init__(
        self,
        templates: CommandTemplates,
        *,
        run: Callable[..., subprocess.CompletedProcess] | None = None,
        timeout: float = 30.0,
    ) -> None:
        raise NotImplementedError

    def show(self, id: str, title: str, body: str, link: str) -> None:
        raise NotImplementedError

    def clear(self, id: str) -> None:
        raise NotImplementedError
