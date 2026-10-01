"""A checkpoint loads only known types (docs/unit-graph.md, Durability).

The state's types are found by walking `UnitRun`'s annotations, so a type added
to the state and left off the allowlist fails here, not on a resume in
production.
"""

from __future__ import annotations

import types
import typing
from datetime import datetime
from enum import Enum
from typing import Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

from agent_build_kit.graph.checkpointer import ALLOWED_MSGPACK_MODULES
from agent_build_kit.graph.state import UnitRun


def reachable(annotation: Any, found: set[type]) -> set[type]:
    """Every model and enum a field's type can hold."""
    if typing.get_origin(annotation) is not None:
        for arg in typing.get_args(annotation):
            reachable(arg, found)
    elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
        found.add(annotation)
        for field in annotation.model_fields.values():
            reachable(field.annotation, found)
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        found.add(annotation)
    return found


def populated(annotation: Any) -> Any:
    """A value of the type with something in every field, nested ones too."""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is tuple:
        return (populated(args[0]),)
    if origin in (typing.Union, types.UnionType):
        return populated(next(arg for arg in args if arg is not type(None)))
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation(
            **{name: populated(f.annotation) for name, f in annotation.model_fields.items()}
        )
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return next(iter(annotation))
    if annotation is bool:
        return True
    if annotation is int:
        return 3
    if annotation is datetime:
        return datetime(2026, 1, 1)
    return "x"


def test_every_type_the_state_uses_is_on_the_allowlist() -> None:
    used = {(cls.__module__, cls.__qualname__) for cls in reachable(UnitRun, set())}

    missing = used - set(ALLOWED_MSGPACK_MODULES)

    assert not missing, f"add to ALLOWED_MSGPACK_MODULES: {sorted(missing)}"


def test_a_checkpoint_holding_every_state_type_loads_with_the_allowlist_in_force() -> None:
    state = populated(UnitRun)
    serde = JsonPlusSerializer(allowed_msgpack_modules=list(ALLOWED_MSGPACK_MODULES))

    loaded = serde.loads_typed(serde.dumps_typed(state))

    assert loaded == state
