"""Running a thread: the one place that sets how it is made durable."""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from agent_build_kit.graph.state import Node


async def run_thread(
    graph: CompiledStateGraph,
    input: Any,
    thread_id: str,
    *,
    interrupt_before: list[Node] | None = None,
) -> Any:
    """Run or resume `thread_id` (`input=None` resumes), each step written to disk first.

    Always `durability="sync"`: the host can lose power at any moment, so a
    step is not done until its checkpoint is on disk (docs/unit-graph.md,
    Durability).
    """
    return await graph.ainvoke(
        input,
        {"configurable": {"thread_id": thread_id}},
        durability="sync",
        interrupt_before=interrupt_before,
    )
