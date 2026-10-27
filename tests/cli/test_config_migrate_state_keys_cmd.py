"""`abk config --migrate` moves a tracked `planning.home` and `planning.state_dir` that leaves the
repository into abk.local.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.cli.config_migrate_fakes import run_migrate
from tests.cli.config_migrate_machine_fakes import tracked
from tests.config_migrate_machine_support import TILDE

BASE = "version: 1\nrepos:\n  app:\n    slug: example/app\n    profile: python-uv\n"


def test_both_keys_move_to_the_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(
        tmp_path,
        BASE + f"planning:\n  home: {TILDE}planning\n  state_dir: {TILDE}state\n",
    )

    code, _ = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    local = yaml.safe_load((tmp_path / "abk.local.yaml").read_text())
    assert local == {"planning": {"home": f"{TILDE}planning", "state_dir": f"{TILDE}state"}}
    assert yaml.safe_load(path.read_text())["planning"] == {}
