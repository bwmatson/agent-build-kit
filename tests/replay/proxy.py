"""The reverse proxy that records and replays the calls of tier-2 tests.

One listener on loopback per configured upstream; the code under test is given the
listener's address through the environment variables the upstream names.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from agent_build_kit.config import ReplayConfig
from agent_build_kit.replay.hosts import InStackHosts
from agent_build_kit.replay.models import ReplayMode, Rule


class InStackUpstream(Exception):
    """A configured upstream whose host is part of the stack."""


class SecretInRecording(Exception):
    """A response body held a configured secret; the test's calls were not stored."""


class ReplayProxy:
    def __init__(
        self,
        config: ReplayConfig,
        mode: ReplayMode,
        *,
        staging: Path,
        in_stack: InStackHosts | None = None,
        secrets: Sequence[str] = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self.mode = mode
        # The test's calls so far that were not recorded because their body was too large.
        self.too_large: list[str] = []
        # The declared rules that applied to a call, in the tests run so far.
        self.rules_used: list[Rule] = []

    def __enter__(self) -> ReplayProxy:
        raise NotImplementedError

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        raise NotImplementedError

    @property
    def addresses(self) -> dict[str, str]:
        """Each upstream's name to its listener's base URL; empty when the mode is `off`."""
        raise NotImplementedError

    def environment(self) -> dict[str, str]:
        """The environment variables, each set to its upstream's listener; empty when `off`."""
        raise NotImplementedError

    def begin(self, test_id: str, rules: Sequence[Rule] = ()) -> None:
        """Calls from here on belong to `test_id`, and `rules` are declared for them."""
        raise NotImplementedError

    def finish(self, *, passed: bool) -> None:
        """Promote the staged calls of the test to the cassette directory, or discard them."""
        raise NotImplementedError
