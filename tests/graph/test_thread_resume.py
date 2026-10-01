"""A unit's thread survives its process: interrupted, or killed mid-node, it
resumes in another process at the same node (docs/unit-graph.md, Durability).

Each process is a real interpreter run against the same SQLite file, so what
is tested is what is on disk, not what one process still remembers.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = """
import asyncio, json, pathlib, sys

from agent_build_kit.graph.build import compile_graph
from agent_build_kit.graph.checkpointer import open_checkpointer
from agent_build_kit.graph.state import Node, UnitRun

db, mode, running, ran = sys.argv[1:5]
config = {"configurable": {"thread_id": "feature/1"}}
unit = UnitRun(unit_id="feature/1", change="feature", groups=(1,))


async def block(state):
    pathlib.Path(running).write_text("running")
    await asyncio.sleep(3600)


async def record(state):
    with open(ran, "a") as out:
        out.write("prepare\\n")
    return {}


async def main():
    async with open_checkpointer(pathlib.Path(db)) as saver:
        if mode == "interrupt":
            graph = compile_graph(saver)
            await graph.ainvoke(
                unit, config, durability="sync", interrupt_before=[Node.PREPARE]
            )
        elif mode == "block":
            graph = compile_graph(saver, work={Node.PREPARE: block})
            await graph.ainvoke(unit, config, durability="sync")
        else:
            graph = compile_graph(saver, work={Node.PREPARE: record})
            before = list((await graph.aget_state(config)).next)
            print(json.dumps({"next_before_resume": before}), flush=True)
            await graph.ainvoke(None, config, durability="sync")


asyncio.run(main())
"""


def start(tmp_path: Path, mode: str) -> subprocess.Popen[str]:
    script = tmp_path / "process.py"
    script.write_text(SCRIPT)
    return subprocess.Popen(
        [
            sys.executable,
            str(script),
            str(tmp_path / "unit-graphs.sqlite"),
            mode,
            str(tmp_path / "running"),
            str(tmp_path / "ran"),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )


def resume_in_a_new_process(tmp_path: Path) -> dict:
    process = start(tmp_path, "resume")
    out, _ = process.communicate(timeout=60)
    assert process.returncode == 0
    return json.loads(out.splitlines()[0])


def test_a_thread_interrupted_in_one_process_resumes_in_another_at_the_same_node(
    tmp_path: Path,
) -> None:
    first = start(tmp_path, "interrupt")
    first.communicate(timeout=60)
    assert first.returncode == 0

    seen = resume_in_a_new_process(tmp_path)

    assert seen["next_before_resume"] == ["prepare"]
    assert (tmp_path / "ran").read_text().splitlines() == ["prepare"], "it ran next, once"


def test_a_process_killed_while_a_node_runs_leaves_the_thread_resumable_at_that_node(
    tmp_path: Path,
) -> None:
    first = start(tmp_path, "block")
    running = tmp_path / "running"
    deadline = time.monotonic() + 30
    while not running.exists():
        if first.poll() is not None or time.monotonic() > deadline:
            first.kill()
            pytest.fail("the node never started")
        time.sleep(0.05)
    first.kill()
    first.wait(timeout=30)

    seen = resume_in_a_new_process(tmp_path)

    assert seen["next_before_resume"] == ["prepare"]
    assert (tmp_path / "ran").read_text().splitlines() == ["prepare"], "the node ran again"
