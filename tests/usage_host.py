"""A host whose usage endpoint is faked at the HTTP boundary.

Only `urllib.request.urlopen` and the home directory are faked, so the guard's
own reading, cache and record run for real. The endpoint answers with the body
it really sends; a test queues the answers, and `asked` counts the calls made.
"""

import io
import json
import urllib.error
import urllib.request
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.claude_account import Account, file_for, resolve_in
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.usage_calls import CALLS_NAME
from agent_build_kit.settings import settings

SECRET = "sk-ant-oat01-the-secret"
HOUR_MS = 3_600_000


def ms_from_now(offset_ms: int) -> int:
    return int(datetime.now(UTC).timestamp() * 1000) + offset_ms


def write_credentials(directory: Path, token: str | None, expires_at_ms: int | None = None) -> None:
    """The `.credentials.json` of the account at `directory`, holding what is given."""
    directory.mkdir(parents=True, exist_ok=True)
    oauth = {"accessToken": token, "expiresAt": expires_at_ms}
    oauth = {key: value for key, value in oauth.items() if value is not None}
    (directory / ".credentials.json").write_text(json.dumps({"claudeAiOauth": oauth}))


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
        # "default": `use_account` points the default account at a directory through the setting;
        # "labelled": it puts a labelled account with that directory in force instead.
        self.account_kind = "default"
        self.account = Account.default()
        self._scope = ExitStack()
        # The default-account tests: no account is set, whatever the process holds.
        monkeypatch.setattr(settings, "claude_home", None)
        self.answers: list[object] = []
        self.asked = 0
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.keep_in(self.home / ".cache" / "agent-build-kit")
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", SECRET)
        monkeypatch.setattr("urllib.request.urlopen", self.urlopen)
        monkeypatch.setattr("time.sleep", lambda _: None)
        config_module.activate(WorkspaceConfig(), None)
        usage_guard.forget_logged_failures()

    def keep_in(self, state_dir: Path) -> None:
        """Where the cache and the record are: the state directory of an active installation."""
        self._cache_base = state_dir / "usage-cache.json"
        self._calls_base = state_dir / CALLS_NAME
        self.cache = self._cache_base
        self.calls_file = self._calls_base

    def close(self) -> None:
        """Leave the account `use_account` put in force."""
        self._scope.close()

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
        body, see `editor_block`). A file with nothing to say is not written. The account is
        the default one at that directory, or, when `account_kind` is "labelled", a labelled
        one in force (`self.account`) with its own cache and record files."""
        directory = self.home / "account"
        directory.mkdir(exist_ok=True)
        # As the registry resolves an account: with the limits the installation sets.
        limits = resolve_in(config_module.active(), None).usage_limits
        if self.account_kind == "labelled":
            self.account = Account(label="personal", config_dir=directory, usage_limits=limits)
            self._scope.enter_context(usage_guard.on_account(self.account))
            self.cache = file_for(self._cache_base, self.account)
            self.calls_file = file_for(self._calls_base, self.account)
        else:
            self.monkeypatch.setattr(settings, "claude_home", directory)
            self.account = Account(usage_limits=limits)
        if token is not None or expires_at_ms is not None:
            write_credentials(directory, token, expires_at_ms)
        if block is not None:
            (directory / ".claude.json").write_text(json.dumps(block))
        return directory

    def refuse_default_state_file(self) -> None:
        """Opening the default account's `~/.claude.json` fails the test, whatever it holds."""
        default = self.home / ".claude.json"
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
        WorkspaceConfig.model_validate({"runtimes": {"claude_code": {"usage_limits": limits}}}),
        None,
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


def reject_login(host: Host, account: Account) -> None:
    """The account's saved token has expired, the endpoint answers 401 and the refresh leaves the
    token as it was: the live reading fails, and the guard keeps why."""
    host.monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    directory = account.config_dir or host.home / ".claude"
    write_credentials(directory, "old-token", ms_from_now(-HOUR_MS))
    host.answers = [unauthorized()]
    with usage_guard.on_account(account):
        assert usage_guard.read_live_usage(refresh=lambda _account: None) is None


def rejection(account: Account) -> str:
    """What status, doctor and the start decision say of a login the endpoint rejected after a
    refresh."""
    name = account.label or "default"
    where = f"CLAUDE_CONFIG_DIR={account.config_dir} " if account.config_dir else ""
    return (
        f"account {name}: the login is rejected (HTTP 401) after a refresh; "
        f"run {where}claude auth login"
    )


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
