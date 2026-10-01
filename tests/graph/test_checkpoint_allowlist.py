"""A checkpoint loads only known types (docs/unit-graph.md, Durability).

The state's types are found by walking `UnitRun`'s annotations, so a type added
to the state and left off the allowlist fails here, not on a resume in
production.
"""

from __future__ import annotations

import asyncio
import types
import typing
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import empty_checkpoint
from pydantic import BaseModel

from agent_build_kit.graph.build import compile_graph
from agent_build_kit.graph.checkpointer import ALLOWED_MSGPACK_MODULES, open_checkpointer
from agent_build_kit.graph.run import run_thread
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


def a_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


def test_a_checkpoint_holding_every_state_type_loads_through_the_real_checkpointer(
    tmp_path: Path,
) -> None:
    db = tmp_path / "unit-graphs.sqlite"
    state = populated(UnitRun)

    async def write() -> None:
        async with open_checkpointer(db) as saver:
            await run_thread(compile_graph(saver), state, "feature/1")

    async def read() -> Any:
        async with open_checkpointer(db) as saver:
            return await compile_graph(saver).aget_state(a_config("feature/1"))

    asyncio.run(write())
    snapshot = asyncio.run(read())

    assert UnitRun.model_validate(snapshot.values) == state


class Unlisted(BaseModel):
    secret: str


def test_a_type_off_the_allowlist_does_not_load_as_that_type(tmp_path: Path) -> None:
    db = tmp_path / "unit-graphs.sqlite"
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"held": Unlisted(secret="x")}

    async def write() -> None:
        async with open_checkpointer(db) as saver:
            await saver.aput(a_config("feature/1"), checkpoint, {"source": "input", "step": 0}, {})

    async def read() -> Any:
        async with open_checkpointer(db) as saver:
            return await saver.aget_tuple(a_config("feature/1"))

    asyncio.run(write())
    loaded = asyncio.run(read())

    assert loaded is not None
    assert not isinstance(loaded.checkpoint["channel_values"].get("held"), Unlisted)
