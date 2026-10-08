"""The server `abk serve` runs: a read API over the unit store, the usage ledger,
the run logs and the checkpoint store, bound to the loopback address only."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import aiosqlite
import uvicorn
from fastapi import FastAPI, HTTPException, Response
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent_build_kit.graph.checkpointer import ALLOWED_MSGPACK_MODULES, unit_graphs_path
from agent_build_kit.graph.unit import thread_position
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.run_log import run_log_dir
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import base_of
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.usage_report import GROUPINGS, build_report, render_json
from agent_build_kit.pipeline.vocabulary import effective_state

HOST = "127.0.0.1"

_STAMPED = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\] ?(.*)$")
_OUTCOME = "outcome: "


def _read_units(path: Path) -> list[StoredUnit]:
    """The stored units, read for display: a field this release does not know is
    left out, where the pipeline's own store refuses the file."""
    if not path.exists():
        return []
    known = set(StoredUnit.model_fields)
    document = json.loads(path.read_text())
    return [
        StoredUnit.model_validate({k: v for k, v in item.items() if k in known})
        for item in document["units"]
    ]


@asynccontextmanager
async def _read_only_checkpointer(path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    # With no write-ahead log beside it nothing is writing, and a plain read-only
    # open would create one; `immutable` reads the file as it stands and creates none.
    wal = path.with_name(f"{path.name}-wal")
    mode = "mode=ro" if wal.exists() and wal.stat().st_size else "mode=ro&immutable=1"
    async with aiosqlite.connect(f"file:{path}?{mode}", uri=True) as conn:
        serde = JsonPlusSerializer(allowed_msgpack_modules=list(ALLOWED_MSGPACK_MODULES))
        yield AsyncSqliteSaver(conn, serde=serde)


def _review_round(installation: Installation, unit_id: str) -> int | None:
    path = unit_graphs_path(installation.state_dir)
    if not path.exists():
        return None

    async def read() -> int | None:
        async with _read_only_checkpointer(path) as saver:
            position = await thread_position(saver, unit_id)
        return position.state.review_round if position.state else None

    return asyncio.run(read())


def _header(path: Path) -> tuple[dict[str, str], int]:
    """A run file's header fields, and the offset its body starts at."""
    fields: dict[str, str] = {}
    with path.open("rb") as file:
        while True:
            raw = file.readline()
            line = raw.decode(errors="replace").strip()
            if not raw or not line:
                return fields, file.tell()
            key, _, value = line.partition(": ")
            fields[key] = value


def _started(fields: dict[str, str]) -> datetime | None:
    try:
        return datetime.fromisoformat(fields["started"]).astimezone(UTC)
    except (KeyError, ValueError):
        return None


def _outcome_of(path: Path) -> str | None:
    """The run's outcome, or None while it has no outcome line (it is live)."""
    found = [
        line for line in path.read_text(errors="replace").splitlines() if line.startswith(_OUTCOME)
    ]
    return found[-1].removeprefix(_OUTCOME) if found else None


def _stamp(previous: datetime, h: int, m: int, s: int) -> datetime:
    """A host-clock time as UTC: on the host's date of the previous line, a day
    on when the clock has passed midnight since."""
    moment = previous.astimezone().replace(hour=h, minute=m, second=s, microsecond=0)
    if moment < previous.astimezone():
        moment = (moment.replace(tzinfo=None) + timedelta(days=1)).astimezone()
    return moment.astimezone(UTC)


def _run_name(change: str, number: str) -> re.Pattern[str]:
    """The names of the run files of unit `change/number`."""
    return re.compile(re.escape(f"{change}-{int(number):02d}-") + r"\d{8}-\d{6}-[\w.-]+\.log")


def _run_files(installation: Installation, change: str, number: str) -> list[Path]:
    directory = run_log_dir(installation.state_dir)
    if not directory.is_dir() or not number.isdigit():
        return []
    pattern = _run_name(change, number)
    return sorted(p for p in directory.iterdir() if pattern.fullmatch(p.name))


def create_app(installation: Installation) -> FastAPI:
    app = FastAPI(title="abk serve", docs_url=None, redoc_url=None, openapi_url=None)
    units_path = installation.state_dir / "units.json"

    def find(change: str, number: str) -> tuple[StoredUnit, list[StoredUnit]]:
        units = _read_units(units_path)
        unit = next((u for u in units if u.id == f"{change}/{number}"), None)
        if unit is None:
            raise HTTPException(status_code=404, detail=f"no unit {change}/{number}")
        return unit, units

    def summary(unit: StoredUnit, units: list[StoredUnit]) -> dict[str, Any]:
        return {
            "id": unit.id,
            "title": unit.title,
            "change": unit.change,
            "repo": unit.repo,
            "state": effective_state(unit, units),
            "cause": unit.cause.value if unit.cause else None,
            "held_by": unit.held_by.value,
            "note": unit.note,
            "branch": unit.branch,
            "pr": unit.pr,
        }

    def related(ids: tuple[str, ...], units: list[StoredUnit]) -> list[dict[str, str]]:
        index = {u.id: u for u in units}
        return [
            {"id": uid, "state": effective_state(index[uid], units) if uid in index else "unknown"}
            for uid in ids
        ]

    @app.get("/api/pipeline")
    def pipeline() -> dict[str, Any]:
        units = _read_units(units_path)
        return {"units": [summary(u, units) for u in units]}

    @app.get("/api/units/{change}/{number}")
    def one_unit(change: str, number: str) -> dict[str, Any]:
        unit, units = find(change, number)
        return {
            **summary(unit, units),
            "history": [
                {
                    "state": entry.get("state"),
                    "at": entry.get("at"),
                    "cause": entry.get("cause") or None,
                    "note": entry.get("note", ""),
                }
                for entry in unit.history
            ],
            "base": base_of(unit, units),
            "depends_on": related(unit.depends_on, units),
            "merge_gates": related(unit.merge_before, units),
            "review_round": _review_round(installation, unit.id),
        }

    @app.get("/api/units/{change}/{number}/logs")
    def run_listing(change: str, number: str) -> dict[str, Any]:
        find(change, number)
        runs = []
        for path in _run_files(installation, change, number):
            try:
                fields, _ = _header(path)
                live = _outcome_of(path) is None
            except OSError:
                continue
            started = _started(fields)
            runs.append(
                {
                    "name": path.name,
                    "step": fields.get("step", ""),
                    "started": started.isoformat() if started else None,
                    "live": live,
                }
            )
        return {"runs": runs}

    @app.get("/api/units/{change}/{number}/logs/{name}")
    def run_lines(change: str, number: str, name: str, offset: int = 0) -> dict[str, Any]:
        find(change, number)
        if not number.isdigit() or not _run_name(change, number).fullmatch(name):
            raise HTTPException(status_code=404, detail=f"no run {name}")
        path = run_log_dir(installation.state_dir) / name
        try:
            fields, body_start = _header(path)
            start = max(offset, body_start)
            with path.open("rb") as file:
                file.seek(start)
                data = file.read()
            outcome = _outcome_of(path)
        except FileNotFoundError:
            return {"lines": [], "offset": offset, "live": False, "outcome": None, "missing": True}
        # Only whole lines: a partly written one is read on the next poll.
        data = data[: data.rfind(b"\n") + 1]
        started = _started(fields)
        clock = started
        lines: list[dict[str, Any]] = []
        for raw in data.decode(errors="replace").splitlines():
            if not raw.strip() or raw.startswith(_OUTCOME):
                continue
            match = _STAMPED.match(raw)
            if match and clock is not None:
                h, m, s = (int(group) for group in match.groups()[:3])
                clock = _stamp(clock, h, m, s)
                lines.append({"at": clock.isoformat(), "text": match.group(4)})
            else:
                lines.append({"at": clock.isoformat() if clock else None, "text": raw})
        return {
            "lines": lines,
            "offset": start + len(data),
            "live": outcome is None,
            "outcome": outcome,
            "missing": False,
        }

    @app.get("/api/usage")
    def usage(
        by: str = "unit",
        since: str | None = None,
        change: str | None = None,
        unit: str | None = None,
        include_estimates: bool = False,
    ) -> Response:
        if by not in GROUPINGS:
            raise HTTPException(status_code=400, detail=f"cannot group by {by!r}")
        try:
            floor = datetime.fromisoformat(since) if since else None
        except ValueError:
            raise HTTPException(status_code=400, detail="since is not a date") from None
        report = build_report(
            installation.state_dir / LEDGER_NAME,
            _read_units(units_path),
            group_by=by,
            since=floor,
            change=change,
            unit=unit,
            include_estimates=include_estimates,
        )
        return Response(render_json(report), media_type="application/json")

    return app


class RunningServer:
    """A server that is listening; leaving its `with` block stops it."""

    def __init__(self, app: FastAPI, port: int) -> None:
        config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    @property
    def host(self) -> str:
        return HOST

    @property
    def port(self) -> int:
        return self._server.servers[0].sockets[0].getsockname()[1]

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def __enter__(self) -> Self:
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the server did not start")
            time.sleep(0.01)
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


def start_server(installation: Installation, *, port: int = 0) -> RunningServer:
    """Listen on the loopback address (any free port when `port` is 0) and serve
    `installation`'s stores."""
    return RunningServer(create_app(installation), port)
