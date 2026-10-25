"""Secret values replaced by their names before text is stored or sent.

The set of known values is gathered from the installation and the settings
(`gather`), held in memory only and shown by name (`Redactor`), and applied by
`Redactor.redact`: each value becomes `[redacted:<NAME>]`, a token-shaped string
the set does not hold becomes `[redacted:token-shape]`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, NamedTuple

from agent_build_kit import settings as settings_module

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation

logger = logging.getLogger(__name__)

# A value shorter than this is not redacted.
MIN_LENGTH = 8

# Heuristics for a secret nobody configured; the set is the guarantee.
_TOKEN_SHAPE = re.compile(
    r"sk-[A-Za-z0-9_-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{36,}"
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|(?<=Bearer )[A-Za-z0-9._~+/=-]{20,}"
)


class Redactor:
    """The known secret values by name; its repr and str show names only.

    `short` and `unset` name (never value) the configured sources the set cannot protect:
    a `verify.env` or `redact` value under `MIN_LENGTH`, and a `redact` name with no value.
    """

    def __init__(
        self,
        values: Mapping[str, str],
        *,
        short: Sequence[str] = (),
        unset: Sequence[str] = (),
    ) -> None:
        self._values = dict(values)
        self.short = tuple(short)
        self.unset = tuple(unset)
        self._pattern = self._compile()

    def _compile(self) -> re.Pattern[str] | None:
        found = sorted(
            {value for value in self._values.values() if len(value) >= MIN_LENGTH},
            key=len,
            reverse=True,
        )
        return re.compile("|".join(map(re.escape, found))) if found else None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._values))

    def add(self, name: str, value: str) -> None:
        self._values[name] = value
        self._pattern = self._compile()

    def _by_value(self, text: str) -> str:
        if self._pattern is None:
            return text
        by_value = {value: name for name, value in self._values.items()}
        return self._pattern.sub(lambda found: f"[redacted:{by_value[found.group()]}]", text)

    def redact(self, text: str) -> str:
        return _TOKEN_SHAPE.sub("[redacted:token-shape]", self._by_value(text))

    def found(self, text: str) -> tuple[str, ...]:
        """The sorted names `redact` would replace in `text`, with `token-shape` when a
        token-shaped string the set does not hold remains after the values."""
        names = {
            name
            for name, value in self._values.items()
            if len(value) >= MIN_LENGTH and value in text
        }
        if _TOKEN_SHAPE.search(self._by_value(text)):
            names.add("token-shape")
        return tuple(sorted(names))

    def __repr__(self) -> str:
        return f"Redactor(names={list(self.names)})"


_active = Redactor({})


class Source(NamedTuple):
    """One place a secret comes from: `value` is None when it cannot be had."""

    name: str
    value: str | None
    origin: str


def sources(installation: Installation) -> list[Source]:
    """Every source of a known value, resolved once: the one enumeration `gather` builds
    the set from."""
    from agent_build_kit.installation import _resolve

    found: list[Source] = []
    for name, provider in installation.config.verify.env.items():
        try:
            found.append(Source(name, _resolve(provider), "verify.env"))
        except Exception:
            found.append(Source(name, None, "verify.env"))
    for field in settings_module.CREDENTIAL_FIELDS:
        found.append(Source(field, str(getattr(settings_module.settings, field)), "settings"))
    env_file = settings_module.readable(installation.env_file)
    for name in installation.config.redact:
        value = settings_module.named_value(name, env_file)
        found.append(Source(name, value or None, "redact"))
    return found


def gather(installation: Installation) -> Redactor:
    """The set the installation's configuration and the settings name."""
    values: dict[str, str] = {}
    failed: list[str] = []
    short: list[str] = []
    unset: list[str] = []
    for source in sources(installation):
        if source.value is None:
            (failed if source.origin == "verify.env" else unset).append(source.name)
            continue
        values[source.name] = source.value
        if source.origin != "settings" and len(source.value) < MIN_LENGTH:
            short.append(f"{source.origin} {source.name}")
    if failed:
        logger.warning("redaction: no value for %s; they are not redacted", ", ".join(failed))
    return Redactor(values, short=short, unset=unset)


def activate(redactor: Redactor) -> None:
    global _active
    _active = redactor


def active() -> Redactor:
    """The set built when the installation was last activated."""
    return _active


def register(name: str, value: str) -> None:
    """Add a value minted during the run to the active set under `name`."""
    _active.add(name, value)


# Stored or posted in place of text that could not be redacted.
WITHHELD = "[redaction failed: text withheld]"


def redact_leaves(value: Any, *, where: str) -> Any:
    """`value` with every string in it, through any dicts and lists, redacted; a string
    whose redaction raises is replaced by the notice.

    One line is logged per call however many strings fail, by the failure's type and
    `where` (the boundary): the exception's message can quote the text.
    """
    failed = False

    def walk(item: Any) -> Any:
        nonlocal failed
        if isinstance(item, str):
            try:
                return _active.redact(item)
            except Exception as error:  # noqa: BLE001 — fails closed for the text, not the run
                if not failed:
                    failed = True
                    logger.warning(
                        "redaction failed in %s (%s); the text was withheld",
                        where,
                        type(error).__name__,
                    )
                return WITHHELD
        if isinstance(item, dict):
            return {key: walk(inner) for key, inner in item.items()}
        if isinstance(item, list | tuple):
            return [walk(inner) for inner in item]
        return item

    return walk(value)


def redact_text(text: str, *, where: str) -> str:
    """`text` through the active set, or the notice when that raises."""
    return redact_leaves(text, where=where)
