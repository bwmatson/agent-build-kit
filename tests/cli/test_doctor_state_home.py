"""`abk doctor` over an in-repo installation whose state is outside the repository: it warns about
state git still tracks under `runs/`, not about ignore lines (spec:
planning-state-external-checks)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from agent_build_kit.cli.doctor import Check
from tests.cli.in_repo_doctor import checks_of, in_repo
from tests.factories import git

RUNBOOK = "move-state-out-of-the-repo"


def default_state(config: Path) -> Path:
    """`config` with no `planning.state_dir`, so the state is the installation's default."""
    document = yaml.safe_load(config.read_text())
    document["planning"].pop("state_dir", None)
    config.write_text(yaml.safe_dump(document))
    return config


def track_legacy_state(root: Path, *names: str) -> None:
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("{}\n")
    git(root, "add", "-f", *names)
    git(root, "commit", "-qm", "the state")


def about_runbook(checks: list[Check]) -> list[Check]:
    return [c for c in checks if RUNBOOK in f"{c.detail} {c.fix}"]


def test_tracked_legacy_state_warns_once_and_the_move_clears_it(tmp_path: Path, data: Path) -> None:
    config = default_state(in_repo(tmp_path / "plan"))
    track_legacy_state(config.parent, "runs/units.json", "runs/health.md")

    found = checks_of(config)

    legacy = about_runbook(found)
    assert [c.status for c in legacy] == ["warn"]
    text = f"{legacy[0].detail} {legacy[0].fix}"
    assert "2 file(s)" in legacy[0].detail
    assert re.search(r"not (been )?moved", text)
    assert not [c for c in found if c.name == "state ignores" and c.status == "warn"]

    git(config.parent, "rm", "-rq", "runs")
    git(config.parent, "commit", "-qm", "move the state out")

    assert about_runbook(checks_of(config)) == []
