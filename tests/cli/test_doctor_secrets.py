"""`abk doctor` warns, by name, about a secret the redaction set would not cover: a
`verify.env` or `redact` variable whose value is under 8 characters, and a `redact` name
that is not set. It never prints a value."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo

SHORT = "sh0rt-7"
LONG = "long-enough-value"


def doctor_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Check]:
    for name in ("SHORT_REDACTED", "LONG_REDACTED", "UNSET_REDACTED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SHORT_REDACTED", SHORT)
    monkeypatch.setenv("LONG_REDACTED", LONG)
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    config = WorkspaceConfig.model_validate(
        {
            "repos": {"app": RepoConfig(path=app, slug="example/app").model_dump(mode="json")},
            "verify": {
                "env": {
                    "SHORT_VERIFY": {"from": "literal", "value": SHORT},
                    "LONG_VERIFY": {"from": "literal", "value": LONG},
                }
            },
            "redact": ["SHORT_REDACTED", "LONG_REDACTED", "UNSET_REDACTED"],
        }
    )
    (planning / "abk.yaml").write_text(dump(config))
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def warned(checks: list[Check]) -> str:
    return "\n".join(f"{c.name} {c.detail} {c.fix}" for c in checks if c.status == "warn")


def test_a_short_or_unset_secret_is_warned_about_by_name_and_no_value_is_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checks = doctor_checks(tmp_path, monkeypatch)

    shown = warned(checks)
    assert "SHORT_VERIFY" in shown
    assert "SHORT_REDACTED" in shown
    assert "UNSET_REDACTED" in shown
    assert "LONG_VERIFY" not in shown
    assert "LONG_REDACTED" not in shown
    everything = "\n".join(f"{c.name} {c.detail} {c.fix}" for c in checks)
    assert SHORT not in everything
    assert LONG not in everything
