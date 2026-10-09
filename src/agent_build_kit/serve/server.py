"""The server `abk serve` runs: a read API over the unit store, the usage ledger,
the run logs and the checkpoint store, plus a unit's review diff and the review store,
bound to the loopback address only."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self

import aiosqlite
import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, PlainTextResponse
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field, model_validator

from agent_build_kit.graph.checkpointer import ALLOWED_MSGPACK_MODULES, unit_graphs_path
from agent_build_kit.graph.unit import thread_position
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.run_log import CONTINUATION, run_log_dir
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import base_of
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.usage_report import GROUPINGS, build_report, render_json
from agent_build_kit.pipeline.vocabulary import effective_state
from agent_build_kit.serve.metrics import dashboard_uid, metrics_page
from agent_build_kit.serve.review import (
    Decision,
    NoDiff,
    ReviewStore,
    Thread,
    branch_tip,
    placed,
    resolve_commit,
    unit_diff,
)
from agent_build_kit.settings import settings

HOST = "127.0.0.1"
# Where `npm run build` in `web/` puts the UI; the wheel ships it from here.
STATIC_DIR = Path(__file__).resolve().parent / "static"

_STAMPED = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\] ?(.*)$")
_OUTCOME = "outcome: "


class ThreadIn(Frozen):
    path: str
    side: Literal["old", "new"] = "new"
    line: int = Field(ge=1)
    start_line: int | None = Field(default=None, ge=1)
    # The commit of the diff the reviewer was looking at; the branch tip when omitted.
    commit: str | None = None
    body: str

    @model_validator(mode="after")
    def _range_runs_forward(self) -> Self:
        if self.start_line is not None and self.start_line > self.line:
            raise ValueError("start_line is after line")
        return self


class ReplyIn(Frozen):
    body: str


class ResolveIn(Frozen):
    resolved: bool


class DecisionIn(Frozen):
    decision: Decision
    summary: str = ""


def _read_units(path: Path) -> list[StoredUnit]:
    """The stored units, read for display."""
    if not path.exists():
        return []
    document = json.loads(path.read_text())
    return [StoredUnit.model_validate(item) for item in document["units"]]


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

    try:
        return asyncio.run(read())
    except (sqlite3.Error, aiosqlite.Error):
        return None


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
    previous = previous.astimezone().replace(microsecond=0)
    moment = previous.replace(hour=h, minute=m, second=s)
    if moment < previous:
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


def create_app(installation: Installation, static_dir: Path = STATIC_DIR) -> FastAPI:
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

    reviews = ReviewStore(installation.state_dir / "reviews")

    def checkout(unit: StoredUnit) -> Path:
        path = installation.checkouts.get(unit.repo)
        if path is None or not unit.branch:
            raise HTTPException(status_code=409, detail=f"{unit.id} has no branch to review")
        return path

    def placed_thread(repo: Path, unit: StoredUnit, thread: Thread) -> dict[str, Any]:
        return placed(repo, thread, branch_tip(repo, unit.branch)).model_dump()

    @app.get("/api/units/{change}/{number}/diff")
    def diff(change: str, number: str, commit: str | None = None) -> dict[str, Any]:
        unit, units = find(change, number)
        repo = checkout(unit)
        try:
            return unit_diff(
                repo, base=base_of(unit, units), branch=unit.branch, commit=commit
            ).model_dump()
        except NoDiff as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.get("/api/units/{change}/{number}/review")
    def review(change: str, number: str) -> dict[str, Any]:
        unit, _ = find(change, number)
        stored = reviews.read(unit.id)
        repo = installation.checkouts.get(unit.repo)
        tip = branch_tip(repo, unit.branch) if repo else None
        threads = [placed(repo, t, tip) for t in stored.threads] if repo else stored.threads
        return {
            "round": _review_round(installation, unit.id) or 1,
            "threads": [t.model_dump() for t in threads],
            "decisions": [d.model_dump() for d in stored.decisions],
        }

    @app.post("/api/units/{change}/{number}/review/threads")
    def add_thread(change: str, number: str, body: ThreadIn) -> dict[str, Any]:
        unit, _ = find(change, number)
        repo = checkout(unit)
        tip = resolve_commit(repo, body.commit) if body.commit else branch_tip(repo, unit.branch)
        if tip is None:
            raise HTTPException(
                status_code=409, detail=f"{body.commit or unit.branch} is not a commit to review"
            )
        thread = reviews.add_thread(
            unit.id,
            path=body.path,
            side=body.side,
            line=body.line,
            start_line=body.start_line,
            commit=tip,
            body=body.body,
        )
        return thread.model_dump()

    def thread_answer(
        change: str, number: str, thread: Callable[[StoredUnit], Thread | None]
    ) -> dict[str, Any]:
        unit, _ = find(change, number)
        found = thread(unit)
        if found is None:
            raise HTTPException(status_code=404, detail="no such thread")
        repo = installation.checkouts.get(unit.repo)
        return placed_thread(repo, unit, found) if repo else found.model_dump()

    @app.post("/api/units/{change}/{number}/review/threads/{thread_id}/replies")
    def reply(change: str, number: str, thread_id: str, body: ReplyIn) -> dict[str, Any]:
        return thread_answer(
            change, number, lambda unit: reviews.reply(unit.id, thread_id, body.body)
        )

    @app.patch("/api/units/{change}/{number}/review/threads/{thread_id}")
    def resolve(change: str, number: str, thread_id: str, body: ResolveIn) -> dict[str, Any]:
        return thread_answer(
            change, number, lambda unit: reviews.resolve(unit.id, thread_id, body.resolved)
        )

    @app.put("/api/units/{change}/{number}/review/decision")
    def decide(change: str, number: str, body: DecisionIn) -> dict[str, Any]:
        unit, _ = find(change, number)
        round_ = _review_round(installation, unit.id) or 1
        verdict = reviews.decide(
            unit.id, round=round_, decision=body.decision, summary=body.summary
        )
        if verdict is None:
            raise HTTPException(status_code=409, detail=f"round {round_} already has a decision")
        return verdict.model_dump()

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
        for raw in data.decode(errors="replace").split("\n")[:-1]:
            if raw.startswith(CONTINUATION):
                if lines:
                    # A further line of the entry before it, its indent taken off.
                    lines[-1]["text"] += "\n" + raw[len(CONTINUATION) :]
                else:
                    # The entry began before this poll's offset: the client
                    # joins this to the last entry it holds.
                    lines.append(
                        {
                            "at": clock.isoformat() if clock else None,
                            "text": raw[len(CONTINUATION) :],
                            "continues": True,
                        }
                    )
                continue
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

    @app.get("/api/metrics")
    def metrics() -> dict[str, Any]:
        grafana = settings.grafana_url.rstrip("/")
        return metrics_page(
            settings.prometheus_url,
            settings.tempo_url,
            installation.state_dir / LEDGER_NAME,
            _read_units(units_path),
            f"{grafana}/d/{dashboard_uid()}" if grafana else None,
            settings.otel_service_name,
        )

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str) -> Response:
        """The built UI: a file it holds, else its index for every route of the
        single-page app. An address under `/api` that no endpoint took stays a JSON 404."""
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"no endpoint /{path}")
        index = static_dir / "index.html"
        if not index.is_file():
            return PlainTextResponse(
                "The web UI is not built: run `npm install && npm run build` in web/.",
                status_code=503,
            )
        asset = (static_dir / path).resolve()
        if path and asset.is_file() and asset.is_relative_to(static_dir.resolve()):
            return FileResponse(asset)
        return FileResponse(index)

    return app


class RunningServer:
    """A server that is listening; leaving its `with` block stops it."""

    def __init__(self, app: FastAPI, port: int) -> None:
        config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        # uvicorn exits the process with a status when it cannot bind; in this thread
        # that must end the thread quietly, `__enter__` reports the failed start.
        try:
            self._server.run()
        except SystemExit:
            pass

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
