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

from pydantic import BaseModel, ConfigDict


class Frozen(BaseModel):
    """An immutable, validated value object."""

    model_config = ConfigDict(frozen=True, extra="forbid")
