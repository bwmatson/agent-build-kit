"""The old spellings of the test kinds, and what each is read as.

Reading goes through here and writing never does: an old spelling found in a heading, an
`abk.yaml` or a state file means the new one, with a notice.
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
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


# The two kinds, by the old name each had: the one table the readers share.
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


def old_tag(tag: str) -> str:
    """The old spelling of a current test-kind tag; any other tag comes back unchanged."""
    return next((old for old, forms in KIND_FORMS.items() if forms.tag == tag), tag)


def old_spelling(kind: TestTier) -> str:
    """The old name of `kind`: `tier1` for the unit-test kind, `tier2` for the e2e-test kind."""
    if (old := old_tag(kind.value)) == kind.value:
        raise ValueError(f"{kind} has no old spelling")
    return old


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


logger = logging.getLogger(__name__)


def moved_to_current_name(directory: Path, name: str, old: str) -> Path:
    """The path of the state file or directory `name` in `directory`. One left under the old
    name `old` is moved to the current one first, with a notice, when it is the only one that
    exists."""
    path = directory / name
    left = directory / old
    if not path.exists() and left.exists():
        # A second process may have moved it first; it is there either way.
        with contextlib.suppress(FileNotFoundError):
            left.rename(path)
            logger.warning(notice(Place.STATE_FILE, old, str(directory)))
    return path
