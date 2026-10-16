"""The old spellings of the test kinds, and what each is read as.

Reading goes through here and writing never does: an old spelling found in a heading, an
`abk.yaml` or a state file means the new one, with a notice.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated

from pydantic import BeforeValidator

from agent_build_kit.model import Frozen, TestTier


class Place(StrEnum):
    """Where an old spelling is found."""

    TAG = "tag"
    SETTING = "setting"
    VALUE = "value"
    STATE_FILE = "state-file"
    METRIC = "metric"


class KindForms(Frozen):
    """The current spellings of one test kind, by where each is written."""

    stem: str  # the part of an identifier, setting or metric name: `e2e_gate`
    file_stem: str  # the part of a state-file or directory name: `e2e-output`
    tag: str  # a tag or stored value: `e2e-test`


# The two kinds, by the old name each had: the one table the readers and the rename tool share.
KIND_FORMS: Mapping[str, KindForms] = MappingProxyType(
    {
        "tier1": KindForms(stem="unit_test", file_stem="unit-test", tag="unit-test"),
        "tier2": KindForms(stem="e2e", file_stem="e2e", tag="e2e-test"),
    }
)

_OLD_STEM = re.compile(r"(?<![a-z0-9])(tier[12])(?=_)")
_OLD_FILE_STEM = re.compile(r"(?<![a-z0-9])(tier[12])(?![a-z0-9])")


def new_spelling(place: Place, name: str) -> str:
    """`name` as the current spelling in `place`; a current spelling comes back unchanged."""
    match place:
        case Place.TAG | Place.VALUE:
            return KIND_FORMS[name].tag if name in KIND_FORMS else name
        case Place.SETTING | Place.METRIC:
            return _OLD_STEM.sub(lambda found: KIND_FORMS[found[1]].stem, name)
        case Place.STATE_FILE:
            return _OLD_FILE_STEM.sub(lambda found: KIND_FORMS[found[1]].file_stem, name)


def old_spelling(kind: TestTier) -> str:
    """The old name of `kind`: `tier1` for the unit-test kind, `tier2` for the e2e-test kind."""
    return next(old for old, forms in KIND_FORMS.items() if forms.tag == kind.value)


def is_old_spelling(place: Place, name: str) -> bool:
    """Whether `name` is an old spelling in `place`."""
    return new_spelling(place, name) != name


def notice(place: Place, old: str, where: str) -> str:
    """The deprecation notice for the old spelling `old` found at `where`."""
    new = new_spelling(place, old)
    if place is Place.TAG:
        old, new = f"[{old}]", f"[{new}]"
    return f"{where}: warning: {place.value} {old} is deprecated; use {new}"


def read_old_kind(value: object) -> object:
    """A test kind as read from a stored value or a heading: an old spelling becomes the new
    one; anything that is not a string (an empty kind, a `TestTier`) comes back unchanged."""
    return new_spelling(Place.VALUE, value) if isinstance(value, str) else value


# A test kind as a model field reads it: either spelling in, a `TestTier` out.
TestKind = Annotated[TestTier, BeforeValidator(read_old_kind)]
