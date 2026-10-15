"""The redaction copies are ignored wherever the state directory is, and both commands that
write one use the same suffix (spec: stored-text-scrub)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.shell import git
from tests.factories import init_repo
from tests.scrub_store_support import pause, planning_installation, run, seed

SUFFIX = ".pre-redact"
SECRET = "history-value-0001"


def template() -> str:
    return resources.files("agent_build_kit").joinpath("templates/gitignore").read_text()


@pytest.fixture
def moved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    """A planning repository with the packaged ignore list and its state under `elsewhere`."""
    inst = planning_installation(
        tmp_path,
        monkeypatch,
        planning=dict(state_dir="elsewhere"),
        verify={"env": {"STACK_KEY": {"from": "literal", "value": SECRET}}},
    )
    init_repo(inst.root)
    (inst.root / ".gitignore").write_text(template())
    return inst


def ignored(inst: Installation, path: Path) -> bool:
    return git(inst.root, "check-ignore", "-q", str(path), check=False).returncode == 0


def test_the_template_ignores_the_copies_at_any_depth() -> None:
    lines = template().splitlines()

    assert "*.pre-redact" in lines
    assert "runs/**/*.pre-redact" not in lines


def test_a_copy_written_under_another_state_directory_is_ignored(moved: Installation) -> None:
    seed(moved)
    pause(moved)

    assert run(moved, "scrub-store", "--apply") == 0

    copy = moved.state_dir / ("units.json" + SUFFIX)
    assert copy.is_file()
    assert ignored(moved, copy)


def test_the_scrub_and_redact_history_write_the_same_suffix(moved: Installation) -> None:
    store = seed(moved)
    pause(moved)

    assert run(moved, "scrub-store", "--apply") == 0
    scrub_copies = sorted(p.name for p in moved.state_dir.glob("*" + SUFFIX))
    store.write_text(store.read_text().replace("tier 2", SECRET))
    (moved.state_dir / ("units.json" + SUFFIX)).unlink()
    assert run(moved, "redact-history", "--apply") == 0

    assert scrub_copies == ["units.json" + SUFFIX]
    assert sorted(p.name for p in moved.state_dir.glob("*" + SUFFIX)) == scrub_copies
    assert SECRET in (moved.state_dir / ("units.json" + SUFFIX)).read_text()
