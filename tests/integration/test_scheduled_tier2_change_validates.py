"""The change written for a due repo passes `abk check` (`openspec validate --strict`) and
`abk tags` (spec: tier2-schedule). Needs node (npx) and, on the first run, the network."""

from __future__ import annotations

import argparse
import shutil

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.e2e_schedule import scheduled_name, write_due
from tests.openspec_cli import require
from tests.tier2_schedule_fakes import TODAY, planning, store_of

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.usefixtures("openspec_cli"),
]


def test_the_written_change_passes_abk_check_and_abk_tags(tmp_path) -> None:
    inst = planning(tmp_path)
    (inst.specs_dir / "specs").mkdir(parents=True, exist_ok=True)
    [name] = write_due(inst, store_of(inst, "app"), today=TODAY, say=lambda line: None)

    require(openspec.validate(inst.root))
    assert cli.cmd_check(argparse.Namespace(), inst) == 0
    assert cli.cmd_tags(argparse.Namespace(all=False, change=name), inst) == 0


def test_every_variants_change_passes_abk_check_and_abk_tags(tmp_path) -> None:
    splits = {"acp": {"marker": "runtime_acp"}, "claude_code": {"marker": "runtime_claude_code"}}
    inst = planning(tmp_path, tests={"tier2_splits": splits})
    (inst.specs_dir / "specs").mkdir(parents=True, exist_ok=True)

    names = write_due(inst, store_of(inst, "app"), today=TODAY, say=lambda line: None)

    assert sorted(names) == [
        scheduled_name("app", TODAY, variant) for variant in ("acp", "claude_code", "rest")
    ]
    require(openspec.validate(inst.root))
    assert cli.cmd_check(argparse.Namespace(), inst) == 0
    for name in names:
        assert cli.cmd_tags(argparse.Namespace(all=False, change=name), inst) == 0
