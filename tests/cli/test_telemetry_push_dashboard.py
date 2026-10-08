"""`abk telemetry push-dashboard`: the framework's dashboard, pushed to a Grafana
named by settings (spec: telemetry).

Grafana is faked at its HTTP boundary: a local server answering the folder and
dashboard endpoints the real API has, with its status codes and JSON bodies, so
what is asserted is what a Grafana would hold after the command ran.
"""

from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import main
from agent_build_kit.settings import reload

TOKEN = "glsa_fixture_token"


@dataclass
class FakeGrafana:
    port: int
    folders: dict[str, str] = field(default_factory=dict)  # uid -> title
    dashboards: dict[str, dict[str, Any]] = field(default_factory=dict)  # uid -> dashboard
    dashboard_folders: dict[str, str] = field(default_factory=dict)  # uid -> folder uid
    auth: list[str | None] = field(default_factory=list)
    refuse_anonymous: int | None = None  # status answered to a request with no credentials
    reject_tokens: int | None = None  # status answered to a request carrying a token

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _handler(grafana: FakeGrafana) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _reply(self, status: int, body: object) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict[str, Any]:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

        def _refused(self) -> bool:
            grafana.auth.append(self.headers.get("Authorization"))
            if grafana.refuse_anonymous and self.headers.get("Authorization") is None:
                self._reply(grafana.refuse_anonymous, {"message": "Unauthorized"})
                return True
            if grafana.reject_tokens and self.headers.get("Authorization") is not None:
                self._reply(grafana.reject_tokens, {"message": "invalid API key"})
                return True
            return False

        def do_GET(self) -> None:
            if self._refused():
                return
            path = self.path.split("?")[0].rstrip("/")
            if path == "/api/folders":
                self._reply(200, [{"uid": u, "title": t} for u, t in grafana.folders.items()])
            elif path.startswith("/api/folders/"):
                uid = path.rsplit("/", 1)[1]
                if uid in grafana.folders:
                    self._reply(200, {"uid": uid, "title": grafana.folders[uid]})
                else:
                    self._reply(404, {"message": "folder not found", "status": "not-found"})
            elif path == "/api/search":
                folders = [
                    {"uid": u, "title": t, "type": "dash-folder"}
                    for u, t in grafana.folders.items()
                ]
                self._reply(200, folders)
            else:
                self._reply(404, {"message": "not found"})

        def do_POST(self) -> None:
            if self._refused():
                return
            body = self._body()
            path = self.path.split("?")[0].rstrip("/")
            if path == "/api/folders":
                if body["uid"] in grafana.folders:
                    self._reply(409, {"message": "a folder with that uid exists"})
                    return
                grafana.folders[body["uid"]] = body["title"]
                self._reply(200, {"uid": body["uid"], "title": body["title"]})
            elif path == "/api/dashboards/db":
                dashboard = body["dashboard"]
                uid = dashboard.get("uid") or dashboard["title"]
                if uid in grafana.dashboards and not body.get("overwrite"):
                    self._reply(
                        412,
                        {"message": "the dashboard was changed", "status": "version-mismatch"},
                    )
                    return
                grafana.dashboards[uid] = dashboard
                grafana.dashboard_folders[uid] = body.get("folderUid", "")
                self._reply(200, {"status": "success", "uid": uid, "slug": "pipeline"})
            else:
                self._reply(404, {"message": "not found"})

    return Handler


@pytest.fixture
def grafana() -> Iterator[FakeGrafana]:
    fake = FakeGrafana(port=0)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    fake.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture(autouse=True)
def clean_grafana_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in ("ABK_GRAFANA_URL", "ABK_GRAFANA_TOKEN", "ABK_GRAFANA_FOLDER"):
        monkeypatch.delenv(key, raising=False)
    yield
    reload(None)


def _configure(monkeypatch: pytest.MonkeyPatch, grafana: FakeGrafana, **extra: str) -> None:
    monkeypatch.setenv("ABK_GRAFANA_URL", grafana.url)
    monkeypatch.setenv("ABK_GRAFANA_TOKEN", TOKEN)
    for key, value in extra.items():
        monkeypatch.setenv(key, value)
    reload(None)


def test_the_first_push_creates_the_folder_and_the_dashboard(
    grafana: FakeGrafana, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, grafana)

    assert main(["telemetry", "push-dashboard"]) == 0

    assert list(grafana.folders.values()) == ["agent-build-kit"]
    (folder_uid,) = grafana.folders
    (dashboard_uid,) = grafana.dashboards
    assert grafana.dashboard_folders[dashboard_uid] == folder_uid
    assert grafana.dashboards[dashboard_uid]["panels"]
    # every call carried the service-account token
    assert grafana.auth and set(grafana.auth) == {f"Bearer {TOKEN}"}


def test_a_second_push_leaves_one_dashboard_in_one_folder(
    grafana: FakeGrafana, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, grafana)

    assert main(["telemetry", "push-dashboard"]) == 0
    first = dict(grafana.dashboards)
    folders = dict(grafana.folders)
    assert main(["telemetry", "push-dashboard"]) == 0

    assert grafana.folders == folders
    assert len(grafana.dashboards) == 1
    assert grafana.dashboards == first


def test_the_folder_name_comes_from_settings(
    grafana: FakeGrafana, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, grafana, ABK_GRAFANA_FOLDER="pipeline-metrics")

    assert main(["telemetry", "push-dashboard"]) == 0

    assert list(grafana.folders.values()) == ["pipeline-metrics"]


def test_a_push_over_a_hand_edited_dashboard_overwrites_it(
    grafana: FakeGrafana, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, grafana)
    assert main(["telemetry", "push-dashboard"]) == 0
    (uid,) = grafana.dashboards
    pushed = dict(grafana.dashboards[uid])
    grafana.dashboards[uid] = {**pushed, "panels": []}

    assert main(["telemetry", "push-dashboard"]) == 0

    assert grafana.dashboards[uid] == pushed


def test_the_planning_repos_env_file_supplies_the_grafana_settings(
    grafana: FakeGrafana, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    planning = tmp_path / "planning"
    planning.mkdir()
    (planning / "abk.yaml").write_text("version: 1\nrepos: {}\n")
    (planning / ".env").write_text(f"ABK_GRAFANA_URL={grafana.url}\nABK_GRAFANA_TOKEN={TOKEN}\n")
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    reload(None)

    code = main(["--config", str(planning / "abk.yaml"), "telemetry", "push-dashboard"])

    assert code == 0
    assert len(grafana.dashboards) == 1


def test_without_a_url_it_names_the_setting_and_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ABK_GRAFANA_TOKEN", TOKEN)
    reload(None)

    code = main(["telemetry", "push-dashboard"])

    captured = capsys.readouterr()
    assert code != 0
    assert "ABK_GRAFANA_URL" in captured.out + captured.err


def _url_only(monkeypatch: pytest.MonkeyPatch, grafana: FakeGrafana) -> None:
    monkeypatch.setenv("ABK_GRAFANA_URL", grafana.url)
    reload(None)


def test_without_a_token_the_push_sends_no_authorization_header(
    grafana: FakeGrafana, monkeypatch: pytest.MonkeyPatch
) -> None:
    _url_only(monkeypatch, grafana)

    assert main(["telemetry", "push-dashboard"]) == 0

    assert list(grafana.folders.values()) == ["agent-build-kit"]
    assert len(grafana.dashboards) == 1
    # the folder lookup, the folder create and the dashboard post, none with credentials
    assert len(grafana.auth) >= 3
    assert set(grafana.auth) == {None}


def test_a_repeat_anonymous_push_leaves_one_dashboard(
    grafana: FakeGrafana, monkeypatch: pytest.MonkeyPatch
) -> None:
    _url_only(monkeypatch, grafana)

    assert main(["telemetry", "push-dashboard"]) == 0
    assert main(["telemetry", "push-dashboard"]) == 0

    assert len(grafana.folders) == 1
    assert len(grafana.dashboards) == 1
    assert set(grafana.auth) == {None}


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_anonymous_push_names_the_token_setting_and_fails(
    status: int,
    grafana: FakeGrafana,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    grafana.refuse_anonymous = status
    _url_only(monkeypatch, grafana)

    code = main(["telemetry", "push-dashboard"])

    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert code != 0
    assert "ABK_GRAFANA_TOKEN" in text
    assert "anonymous" in text
    assert grafana.url in text
    assert not grafana.dashboards


@pytest.mark.parametrize("status", [401, 403])
def test_a_refusal_with_a_token_does_not_blame_the_missing_token(
    status: int,
    grafana: FakeGrafana,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # a Grafana that rejects the bearer token itself
    grafana.reject_tokens = status
    _configure(monkeypatch, grafana)

    code = main(["telemetry", "push-dashboard"])

    captured = capsys.readouterr()
    assert code != 0
    assert "anonymous" not in captured.out + captured.err
