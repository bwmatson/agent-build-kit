"""The allowlisting proxy: the one way a confined process reaches the network."""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType


class Proxy:
    """Listens on a free local port; passes a request to an allowed host (exact or `*.suffix`)
    and answers 403 naming the host for any other. A context manager: leaving stops and joins it."""

    def __init__(self, hosts: Sequence[str]) -> None:
        raise NotImplementedError

    @property
    def port(self) -> int:
        raise NotImplementedError

    def __enter__(self) -> Proxy:
        raise NotImplementedError

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        raise NotImplementedError
