"""`abk doctor` says whether a configured Grafana is used with a token or anonymously."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump
from agent_build_kit.settings import reload
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo

URL = "http://grafana.example:3000"


@pytest.fixture(autouse=True)
def clean_grafana_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in ("ABK_GRAFANA_URL", "ABK_GRAFANA_TOKEN", "ABK_GRAFANA_FOLDER"):
        monkeypatch.delenv(key, raising=False)
    reload(None)
    yield
    monkeypatch.undo()
    reload(None)


def grafana_checks(tmp_path: Path) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    config = WorkspaceConfig(repos={"app": RepoConfig(path=app, slug="example/app")})
    (planning / "abk.yaml").write_text(dump(config))
    checks = run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)
    return [check for check in checks if check.name.startswith("grafana")]


def test_a_url_and_a_token_is_reported_as_the_token_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ABK_GRAFANA_URL", URL)
    monkeypatch.setenv("ABK_GRAFANA_TOKEN", "glsa_fixture_token")
    reload(None)

    (check,) = grafana_checks(tmp_path)

    assert check.name == "grafana"
    assert check.status == "ok"
    assert check.detail == f"{URL} (token)"


def test_a_url_alone_is_reported_as_anonymous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ABK_GRAFANA_URL", URL)
    reload(None)

    (check,) = grafana_checks(tmp_path)

    assert check.name == "grafana"
    assert check.status == "ok"
    assert check.detail == f"{URL} (anonymous)"


def test_no_url_reports_nothing_about_grafana(tmp_path: Path) -> None:
    assert grafana_checks(tmp_path) == []
