"""A host whose usage endpoint is faked at the HTTP boundary.

Only `urllib.request.urlopen` and the home directory are faked, so the guard's
own reading, cache and record run for real. The endpoint answers with the body
it really sends; a test queues the answers, and `asked` counts the calls made.
"""

import io
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.usage_calls import CALLS_NAME
from agent_build_kit.settings import settings

SECRET = "sk-ant-oat01-the-secret"
HOUR_MS = 3_600_000


def ms_from_now(offset_ms: int) -> int:
    return int(datetime.now(UTC).timestamp() * 1000) + offset_ms


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


def unauthorized() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        usage_guard.USAGE_URL, 401, "Unauthorized", Message(), io.BytesIO(b"")
    )


def server_error() -> urllib.error.HTTPError:
    message = Message()
    message["Content-Type"] = "application/json"
    return urllib.error.HTTPError(
        usage_guard.USAGE_URL, 500, "Internal Server Error", message, io.BytesIO(b"")
    )


def faked_paths(home: Path) -> dict[str, Path]:
    """The guard's credential and anchor paths, moved under `home` so no test reads the
    developer's own files; the parent and a spawned asker both apply these."""
    return {
        "CREDENTIALS_PATH": home / "no-credentials.json",
        "DEFAULT_ANCHOR_PATH": home / ".claude.json",
    }


def editor_block(age: timedelta, *, session: int, resets_in: timedelta) -> dict:
    """The block `cachedUsageUtilization` of a `.claude.json`, fetched `age` ago, as Claude Code
    writes it."""
    fetched = datetime.now(UTC) - age
    resets = (datetime.now(UTC) + resets_in).isoformat()
    return {
        "cachedUsageUtilization": {
            "fetchedAtMs": int(fetched.timestamp() * 1000),
            "utilization": {
                "five_hour": {"utilization": session, "resets_at": resets},
                "seven_day": {"utilization": 5, "resets_at": resets},
            },
        }
    }


class Host:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        # The default-account tests: no account is set, whatever the process holds.
        monkeypatch.setattr(settings, "claude_home", None)
        self.answers: list[object] = []
        self.asked = 0
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.keep_in(self.home / ".cache" / "agent-build-kit")
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", SECRET)
        for name, value in faked_paths(self.home).items():
            monkeypatch.setattr(usage_guard, name, value)
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

    def record_bearers(self) -> list[str | None]:
        """Wrap the endpoint so each request's Authorization header is appended to the list
        returned, in the order asked."""
        sent: list[str | None] = []

        def urlopen(request: urllib.request.Request, timeout: float | None = None) -> Response:
            sent.append(request.get_header("Authorization"))
            return self.urlopen(request, timeout)

        self.monkeypatch.setattr("urllib.request.urlopen", urlopen)
        return sent

    def keep_reading(self, age: timedelta, body: dict | None = None) -> None:
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        fetched = datetime.now(UTC) - age
        self.cache.write_text(
            json.dumps({**(body or payload()), "fetched_at": fetched.isoformat()})
        )

    def keep_editor_reading(
        self, age: timedelta, *, session: int = 20, resets_in: timedelta = timedelta(hours=2)
    ) -> None:
        """The editor's own reading in `~/.claude.json`, taken `age` ago, as it writes it."""
        (self.home / ".claude.json").write_text(
            json.dumps(editor_block(age, session=session, resets_in=resets_in))
        )

    def use_account(
        self,
        *,
        token: str | None = None,
        expires_at_ms: int | None = None,
        block: dict | None = None,
    ) -> Path:
        """Set the account to a directory of its own and write its two files: the credentials
        with `token` and `expires_at_ms`, and the state file with `block` (a `.claude.json`
        body, see `editor_block`). A file with nothing to say is not written."""
        account = self.home / "account"
        account.mkdir(exist_ok=True)
        self.monkeypatch.setattr(settings, "claude_home", account)
        oauth = {"accessToken": token, "expiresAt": expires_at_ms}
        oauth = {key: value for key, value in oauth.items() if value is not None}
        if oauth:
            (account / ".credentials.json").write_text(json.dumps({"claudeAiOauth": oauth}))
        if block is not None:
            (account / ".claude.json").write_text(json.dumps(block))
        return account

    def refuse_default_state_file(self) -> None:
        """Opening the default account's `~/.claude.json` fails the test, whatever it holds."""
        default = usage_guard.DEFAULT_ANCHOR_PATH
        reads = (Path.read_text, Path.read_bytes, Path.open)

        def guarded(original):
            def read(path, *args, **kwargs):
                if path == default:
                    raise AssertionError(f"the default account's {default} was opened")
                return original(path, *args, **kwargs)

            return read

        for original in reads:
            self.monkeypatch.setattr(Path, original.__name__, guarded(original))

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


def refused(
    host: Host, ago: timedelta = timedelta(minutes=2), *, cooling: timedelta | None = None
) -> None:
    """The record shows a 429 with a retry time of zero `ago` ago; with `cooling`, a cool-down
    ending that long from now is kept in the cache file beside the reading."""
    host.seed(
        {
            "at": (datetime.now(UTC) - ago).isoformat(),
            "caller": "guard",
            "outcome": "rate_limited",
            "status": 429,
            "latency_ms": 100,
            "headers": {"retry-after": "0"},
        }
    )
    if cooling is not None:
        kept = json.loads(host.cache.read_text())
        until = datetime.now(UTC) + cooling
        host.cache.write_text(json.dumps({**kept, "cooldown_until": until.isoformat()}))


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
