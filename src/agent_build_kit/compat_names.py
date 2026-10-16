"""The old spellings of the test kinds, and what each is read as.

Reading goes through here and writing never does: an old spelling found in a heading, an
`abk.yaml` or a state file means the new one, with a notice.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated

from pydantic import BeforeValidator

from agent_build_kit.model import TestTier


class Place(StrEnum):
    """Where an old spelling is found."""

    TAG = "tag"
    SETTING = "setting"
    VALUE = "value"
    STATE_FILE = "state-file"
    METRIC = "metric"


# The two kinds: what each old name means, as a tag or a stored value, and as the stem of a
# setting, a metric or a state-file name.
_KIND_OF_TAG = {"tier1": "unit-test", "tier2": "e2e-test"}
_STEM = {"tier1": "unit_test", "tier2": "e2e"}
_FILE_STEM = {"tier1": "unit-test", "tier2": "e2e"}

_OLD_STEM = re.compile(r"(?<![a-z0-9])(tier[12])(?=_)")
_OLD_FILE_STEM = re.compile(r"(?<![a-z0-9])(tier[12])(?![a-z0-9])")


def new_spelling(place: Place, name: str) -> str:
    """`name` as the current spelling in `place`; a current spelling comes back unchanged."""
    match place:
        case Place.TAG | Place.VALUE:
            return _KIND_OF_TAG.get(name, name)
        case Place.SETTING | Place.METRIC:
            return _OLD_STEM.sub(lambda found: _STEM[found[1]], name)
        case Place.STATE_FILE:
            return _OLD_FILE_STEM.sub(lambda found: _FILE_STEM[found[1]], name)


def is_old_spelling(place: Place, name: str) -> bool:
    """Whether `name` is an old spelling in `place`."""
    return new_spelling(place, name) != name


def notice(place: Place, old: str, where: str) -> str:
    """The deprecation notice for the old spelling `old` found at `where`."""
    new = new_spelling(place, old)
    if place is Place.TAG:
        old, new = f"[{old}]", f"[{new}]"
    return f"{where}: warning: {place.value} {old} is deprecated; use {new}"


def _read_old_kind(value: object) -> object:
    return new_spelling(Place.VALUE, value) if isinstance(value, str) else value


# A test kind as a model field reads it: either spelling in, a `TestTier` out.
TestKind = Annotated[TestTier, BeforeValidator(_read_old_kind)]
