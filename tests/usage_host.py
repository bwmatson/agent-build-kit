"""A host whose usage endpoint is faked at the HTTP boundary.

Only `urllib.request.urlopen` and the home directory are faked, so the guard's
own reading, cache and record run for real. The endpoint answers with the body
it really sends; a test queues the answers, and `asked` counts the calls made.
"""

import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.usage_calls import CALLS_NAME

SECRET = "sk-ant-oat01-the-secret"


def payload(
    *,
    session: float = 14.0,
    weekly: float = 6.0,
    session_resets_in: timedelta = timedelta(hours=2),
    weekly_resets_in: timedelta = timedelta(days=3),
) -> dict:
    now = datetime.now(UTC)
    return {
        "five_hour": {
            "utilization": session,
            "resets_at": (now + session_resets_in).isoformat(),
        },
        "seven_day": {
            "utilization": weekly,
            "resets_at": (now + weekly_resets_in).isoformat(),
        },
        "extra_usage": {
            "is_enabled": True,
            "monthly_limit": 10000,
            "used_credits": 1324.0,
            "spend_limit_reached": False,
        },
    }


class Response:
    def __init__(self, body: object) -> None:
        self._raw = io.BytesIO(json.dumps(body).encode())

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, *args: int) -> bytes:
        return self._raw.read(*args)


def refusal(**headers: str) -> urllib.error.HTTPError:
    message = Message()
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    return urllib.error.HTTPError(
        usage_guard.USAGE_URL, 429, "Too Many Requests", message, io.BytesIO(b"")
    )


def server_error() -> urllib.error.HTTPError:
    message = Message()
    message["Content-Type"] = "application/json"
    return urllib.error.HTTPError(
        usage_guard.USAGE_URL, 500, "Internal Server Error", message, io.BytesIO(b"")
    )


class Host:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.answers: list[object] = []
        self.asked = 0
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.keep_in(self.home / ".cache" / "agent-build-kit")
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", SECRET)
        monkeypatch.setattr(usage_guard, "CREDENTIALS_PATH", self.home / "no-credentials.json")
        monkeypatch.setattr(usage_guard, "DEFAULT_ANCHOR_PATH", self.home / ".claude.json")
        monkeypatch.setattr("urllib.request.urlopen", self.urlopen)
        monkeypatch.setattr("time.sleep", lambda _: None)
        config_module.activate(WorkspaceConfig(), None)
        usage_guard.forget_logged_failures()

    def keep_in(self, state_dir: Path) -> None:
        """Where the cache and the record are: the state directory of an active installation."""
        self.cache = state_dir / "usage-cache.json"
        self.calls_file = state_dir / CALLS_NAME

    def urlopen(self, request: object, timeout: float | None = None) -> Response:
        self.asked += 1
        answer = self.answers.pop(0) if self.answers else TimeoutError("timed out")
        if isinstance(answer, BaseException):
            raise answer
        return Response(answer)

    def keep_reading(self, age: timedelta, body: dict | None = None) -> None:
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        fetched = datetime.now(UTC) - age
        self.cache.write_text(
            json.dumps({**(body or payload()), "fetched_at": fetched.isoformat()})
        )

    def lines(self) -> list[dict]:
        if not self.calls_file.exists():
            return []
        return [json.loads(line) for line in self.calls_file.read_text().splitlines() if line]

    def seed(self, *lines: dict) -> None:
        self.calls_file.parent.mkdir(parents=True, exist_ok=True)
        self.calls_file.write_text("".join(json.dumps(each) + "\n" for each in lines))


def configure(**limits: object) -> None:
    """The Claude limits an installation sets, over the defaults."""
    config_module.activate(
        WorkspaceConfig.model_validate({"runtimes": {"claude_code": {"limits": limits}}}), None
    )


def pause_at(percent: int, **window: object) -> dict:
    return {
        "session": {"usage_pause_pct": percent, **window},
        "weekly": {"usage_pause_pct": percent, **window},
    }


def called(host: Host, ago: timedelta, outcome: str = "ok") -> None:
    """The record shows a call to the endpoint `ago` ago."""
    host.seed(
        {
            "at": (datetime.now(UTC) - ago).isoformat(),
            "caller": "guard",
            "outcome": outcome,
            "status": 200 if outcome == "ok" else None,
            "latency_ms": 100,
            "headers": {},
        }
    )
