"""The server `abk serve` runs: a read API over the unit store, the usage ledger,
the run logs and the checkpoint store, bound to the loopback address only."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from agent_build_kit.installation import Installation


class RunningServer:
    """A server that is listening; leaving its `with` block stops it."""

    @property
    def host(self) -> str:
        raise NotImplementedError

    @property
    def port(self) -> int:
        raise NotImplementedError

    @property
    def url(self) -> str:
        raise NotImplementedError

    def __enter__(self) -> Self:
        raise NotImplementedError

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        raise NotImplementedError


def start_server(installation: Installation, *, port: int = 0) -> RunningServer:
    """Listen on the loopback address (any free port when `port` is 0) and serve
    `installation`'s stores."""
    raise NotImplementedError
