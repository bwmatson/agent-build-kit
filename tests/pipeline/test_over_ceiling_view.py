"""Where a unit that landed over the ceiling shows: its node on the graph page
and a line of `abk status`."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges import FileChange, RepoId
from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.wiring import build_open_pr
from tests.conftest import make_installation
from tests.factories import activate_with
from tests.factories import stored_unit as unit
from tests.factories import unit as plan_unit

REPO = RepoId(forge="fake", account="example", name="app")


class SizedForge:
    name = "fake"
    implemented = True
    supports_stacks = False

    def __init__(self, lines: int) -> None:
        self.lines = lines

    def find_pr(self, repo, *, head):
        return None

    def create_pr(self, repo, *, head, base, title, body):
        return 1

    def update_pr(self, repo, pr, *, base="", body=""):
        pass

    def pr_changes(self, repo, pr):
        return [FileChange(path="src/app.py", additions=self.lines, deletions=0)]

    def stack_of(self, repo, pr):
        raise AssertionError("a host without stacks was asked about one")

    def create_stack(self, repo, pulls):
        raise AssertionError("a host without stacks was asked about one")

    def add_to_stack(self, repo, stack, pulls):
        raise AssertionError("a host without stacks was asked about one")


def node_of(diagram: str, unit_id: str) -> str:
    return next(line for line in diagram.splitlines() if line.strip().startswith(unit_id))


def test_the_graph_page_marks_a_unit_that_landed_over_the_ceiling() -> None:
    activate_with(limits={"min_unit_lines": 400, "max_unit_lines": 750})
    diagram = render_mermaid(
        [
            unit("big", estimated_lines=600, actual_lines=1400),
            unit("exact", estimated_lines=600, actual_lines=750),
            unit("small", estimated_lines=600, actual_lines=300),
            unit("none", estimated_lines=600),
        ]
    )

    assert "over the ceiling" in node_of(diagram, "big")
    assert "1400" in node_of(diagram, "big")
    for fine in ("exact", "small", "none"):
        assert "over the ceiling" not in node_of(diagram, fine)


def test_status_lists_the_units_over_the_ceiling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(tmp_path)
    activate_with(limits={"min_unit_lines": 400, "max_unit_lines": 750})
    store = cli.store_for(inst)
    store.upsert([unit(f"a/{n}", estimated_lines=600) for n in (1, 2, 3)])
    for n, lines in ((1, 1400), (2, 700)):
        store.set_state(f"a/{n}", IN_REVIEW, pr=n, branch=f"spec/a/{n}")
        open_pr = build_open_pr(
            for_repo=lambda repo, lines=lines: (SizedForge(lines), REPO), store=store
        )
        open_pr(
            plan_unit(f"a/{n}", change="a", estimated_lines=600),
            body="b",
            base="main",
            cwd=tmp_path,
        )
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), inst)

    output = capsys.readouterr()
    lines = [line for line in (output.out + output.err).splitlines() if "over the ceiling" in line]
    assert len(lines) == 1
    assert "a/1" in lines[0] and "1400" in lines[0] and "600" in lines[0]
    assert "a/2" not in lines[0] and "a/3" not in lines[0]
