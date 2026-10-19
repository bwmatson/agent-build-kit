"""The base every value object in this repo is built on.

Pydantic rather than `dataclasses` because most of these objects are parsed
from something outside the process — the unit store on disk, Anthropic's usage
endpoint, `gh`'s JSON — and validation at that boundary is the whole point. A
dataclass accepts whatever it is handed and the mistake surfaces later, in a
subscript or a format string, a long way from the file or the response that
caused it.

Two settings, both deliberate:

- **Frozen.** These are values, not state. The one object that owns mutable
  state, `UnitStore`, is a plain class that reads and writes a file.
- **`extra="forbid"`.** A key we don't know about is a signal that a file or
  an API has moved on without us, and it should say so here rather than be
  dropped silently and rediscovered as a missing field.
"""

from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Frozen(BaseModel):
    """An immutable, validated value object."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# The e2e-test lock's file name in the state directory.
E2E_LOCK_FILE = "e2e.lock"


class TestTier(StrEnum):
    """The kind of a test, by width: a unit test, an integration test (behaviour across modules
    or files in the ordinary suite, a label that behaves as a unit test), or an end-to-end test
    on the local stack."""

    __test__ = False

    UNIT_TEST = "unit-test"
    INTEGRATION_TEST = "integration-test"
    E2E_TEST = "e2e-test"


def widest_kind(kinds: Iterable[TestTier]) -> TestTier:
    """The widest of `kinds` by the order unit-test, integration-test, e2e-test."""
    order = list(TestTier)
    return max(kinds, key=order.index)


def pooled_kind(kind: TestTier) -> TestTier:
    """The kind a calibration ratio is keyed by: integration-test counts as unit-test."""
    return TestTier.UNIT_TEST if kind is TestTier.INTEGRATION_TEST else kind
