"""`abk outlines`: the report of each outline's distance and overlaps, read-only."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import run_support
from agent_build_kit.cli.outlines_cmd import cmd_outlines
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.units import UnitState
from tests.conftest import make_installation
from tests.factories import stored_unit


def planning(tmp_path: Path) -> Installation:
    return make_installation(tmp_path, planning=dict(state_dir="."))


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def outline(inst: Installation, name: str, *lines: str) -> None:
    body = (
        f"# {name}\n\nInitiative: grow — wave 1: {name}\n\n"
        "## Groups (sketch)\n1. [app] [unit-test] A\n\n"
    )
    write(inst.root / "openspec/outlines" / name / "proposal.md", body + "\n".join(lines) + "\n")


def run(inst: Installation, capsys: pytest.CaptureFixture[str], *, overlaps: bool = False):
    capsys.readouterr()
    code = cmd_outlines(argparse.Namespace(overlaps=overlaps), inst)
    return code, capsys.readouterr().out


def files_under(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_each_outline_is_listed_once_nearest_first_with_the_ready_one_marked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = planning(tmp_path)
    write(inst.changes_dir / "base" / "tasks.md", "## 1. [app] [unit-test] Work\n")
    outline(inst, "far", "Waits on: base group 3 — needs it")
    outline(inst, "next", "Waits on: base group 1 — needs it")
    store = run_support.store_for(inst)
    store.upsert([stored_unit("base/1", change="base", groups=(1,))])
    store.set_state("base/1", UnitState.RUNNING)
    before = files_under(inst.root)
    units_before = store.all()

    code, out = run(inst, capsys)

    lines = out.splitlines()
    assert code == 0
    assert [line for line in lines if "next" in line and "ready to detail" in line]
    assert not [line for line in lines if "far" in line and "ready to detail" in line]
    assert sum("next" in line for line in lines) == 1
    assert sum("far" in line for line in lines) == 1
    assert out.index("next") < out.index("far")
    assert files_under(inst.root) == before
    assert run_support.store_for(inst).all() == units_before


def test_overlaps_name_the_change_the_outline_and_its_reworks_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = planning(tmp_path)
    write(
        inst.changes_dir / "feature" / "tasks.md",
        "- [ ] 1.1 Edit `packages/core/src/agent_build_kit/config.py`\n",
    )
    outline(
        inst,
        "later",
        "Touches: `packages/core/**`",
        "Reworks: feature — a",
        "Reworks: feature — b",
        "Reworks: feature — c",
    )
    outline(inst, "docs-only", "Touches: `docs/**`")

    code, out = run(inst, capsys, overlaps=True)

    hit = [line for line in out.splitlines() if "feature" in line and "later" in line]
    assert code == 0
    assert hit and "3" in hit[0] and "promote earlier" in hit[0]
    assert not [line for line in out.splitlines() if "feature" in line and "docs-only" in line]


@pytest.mark.parametrize("overlaps", [False, True], ids=["plain", "overlaps"])
@pytest.mark.parametrize("folder", ["missing", "empty"])
def test_no_outlines_prints_nothing_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], folder: str, overlaps: bool
) -> None:
    inst = planning(tmp_path)
    if folder == "empty":
        (inst.root / "openspec/outlines").mkdir(parents=True)

    assert run(inst, capsys, overlaps=overlaps) == (0, "")
