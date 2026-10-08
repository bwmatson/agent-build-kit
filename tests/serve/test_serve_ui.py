"""`abk serve` serves the built UI: its files, and its index for every page route."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_build_kit.installation import Installation
from agent_build_kit.serve.server import create_app
from tests.serving import seed_pipeline

INDEX = "<!doctype html><title>abk</title><div id=root></div>"


@pytest.fixture
def built(tmp_path: Path) -> Path:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(INDEX)
    (static / "assets" / "app.js").write_text("console.log('abk')")
    (tmp_path / "secret.txt").write_text("not for the web")
    return static


@pytest.fixture
def ui(inst: Installation, built: Path) -> TestClient:
    seed_pipeline(inst)
    return TestClient(create_app(inst, built))


@pytest.mark.parametrize("path", ["/", "/usage", "/units/feature/1"])
def test_a_page_route_answers_the_index(ui: TestClient, path: str) -> None:
    answer = ui.get(path)

    assert answer.status_code == 200
    assert answer.text == INDEX


def test_a_built_file_is_served_as_it_is(ui: TestClient) -> None:
    assert ui.get("/assets/app.js").text == "console.log('abk')"


def test_a_path_outside_the_built_files_is_not_served(ui: TestClient) -> None:
    answer = ui.get("/%2e%2e/secret.txt")

    assert "not for the web" not in answer.text


def test_an_unknown_api_address_stays_a_json_404(ui: TestClient) -> None:
    for path in ("/api/nothing", "/api/units/feature/99"):
        answer = ui.get(path)
        assert answer.status_code == 404
        assert answer.headers["content-type"] == "application/json"
        assert "detail" in answer.json()


def test_the_api_is_still_answered_beside_the_pages(ui: TestClient) -> None:
    assert len(ui.get("/api/pipeline").json()["units"]) == 9


def test_without_a_build_a_page_route_says_how_to_build(inst: Installation, tmp_path: Path) -> None:
    answer = TestClient(create_app(inst, tmp_path / "missing")).get("/")

    assert answer.status_code == 503
    assert "npm run build" in answer.text
