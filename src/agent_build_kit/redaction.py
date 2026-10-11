"""Secret values replaced by their names before text is stored or sent.

The set of known values is gathered from the installation and the settings
(`gather`), held in memory only and shown by name (`Redactor`), and applied by
`Redactor.redact`: each value becomes `[redacted:<NAME>]`, a token-shaped string
the set does not hold becomes `[redacted:token-shape]`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation

# A value shorter than this is not redacted.
MIN_LENGTH = 8


class Redactor:
    """The known secret values by name; its repr and str show names only."""

    def __init__(self, values: Mapping[str, str]) -> None:
        raise NotImplementedError

    @property
    def names(self) -> tuple[str, ...]:
        raise NotImplementedError

    def redact(self, text: str) -> str:
        raise NotImplementedError


def gather(installation: Installation) -> Redactor:
    """The set the installation's configuration and the settings name."""
    raise NotImplementedError


def active() -> Redactor:
    """The set built when the installation was last activated."""
    raise NotImplementedError


def register(name: str, value: str) -> None:
    """Add a value minted during the run to the active set under `name`."""
    raise NotImplementedError
