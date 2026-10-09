"""Chat with a unit's agent session, and the sessions page (docs/architecture.md).

A turn is one agent call whose events stream back as AG-UI events. The first turn on a unit
takes its lease, which the tick respects; a page is a tab with an open event stream, and
its closing releases the leases it took (once the turns it started have ended) and denies
the permission requests it left open.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent_build_kit import runtimes
from agent_build_kit.graph.state import AgentSession
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.transcript import (
    Transcript,
    TranscriptEvent,
    read_file_events,
    read_transcripts,
    transcript_dir,
    unit_transcript_files,
)
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.vocabulary import effective_state
from agent_build_kit.pipeline.workspaces import worktree_path
from agent_build_kit.runtimes.base import (
    AgentRequest,
    AgentResult,
    PermissionAsk,
    SessionUnavailable,
    ToolPolicy,
)
from agent_build_kit.serve.bridge import AgUiEncoder, messages_snapshot
from agent_build_kit.serve.sessions import (
    claude_events,
    claude_home,
    claude_sessions,
    holding_pids,
)

CLAUDE = "claude_code"
ACP = "acp"
POLL_SECONDS = 0.1
ANSWER_POLL_SECONDS = 0.1


class Attachment(BaseModel):
    file: str
    lines: tuple[int, int]
    hunk: str = ""
    text: str = ""


class Turn(BaseModel):
    tab: str = ""
    prompt: str
    attachments: list[Attachment] = []


class NewSession(Turn):
    runtime: str
    model: str = ""
    unit: str | None = None
    repo: str | None = None


class Answer(BaseModel):
    option: str


def with_attachments(prompt: str, attachments: list[Attachment]) -> str:
    """The prompt with each attachment put in as an editor puts in its selection."""
    if not attachments:
        return prompt
    parts = [prompt, "", "Attached context:"]
    for item in attachments:
        parts += [
            "",
            f"File: {item.file}, lines {item.lines[0]}-{item.lines[1]}",
            "Diff hunk:",
            item.hunk,
            "Selected text:",
            item.text,
        ]
    return "\n".join(parts)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _seed(history: list[dict[str, Any]], prompt: str) -> str:
    """A new session's first prompt: the earlier session's history, then the turn."""
    lines = ["This session continues an earlier one. What was said and done in it:", ""]
    for event in history:
        kind = event.get("kind")
        if kind in ("text", "user"):
            who = "user" if kind == "user" else event.get("role", "assistant")
            lines.append(f"{who}: {event.get('text', '')}")
        elif kind == "tool_call":
            lines.append(
                f"[tool call] {event.get('tool', '')} {json.dumps(event.get('input', {}))}"
            )
        elif kind == "tool_result":
            lines.append(f"[tool result] {event.get('text', '')}")
    return "\n".join([*lines, "", prompt])


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=409, detail=detail)


class Chat:
    def __init__(
        self,
        installation: Installation,
        *,
        units: Callable[[], list[StoredUnit]],
        recorded_session: Callable[[str], AgentSession | None],
    ) -> None:
        self.installation = installation
        self._units = units
        self._recorded = recorded_session
        self.leases = Leases(lease_dir(installation.state_dir))
        self.transcripts = transcript_dir(installation.state_dir)
        self._lock = threading.Lock()
        self._busy: set[str] = set()  # sessions a turn of this server is running on
        self._turns: dict[str, int] = {}  # running turns, by the tab that started them
        self._closing: set[str] = set()  # tabs that closed while a turn of theirs ran
        self._closed: dict[str, threading.Event] = {}
        self._stopping = threading.Event()
        self._asks: dict[str, tuple[threading.Event, list[str | None]]] = {}

    # --- units ----------------------------------------------------------------------

    def unit(self, change: str, number: str) -> StoredUnit:
        unit = next((u for u in self._units() if u.id == f"{change}/{number}"), None)
        if unit is None:
            raise HTTPException(status_code=404, detail=f"no unit {change}/{number}")
        return unit

    def worktree(self, unit: StoredUnit) -> Path | None:
        if not unit.branch or unit.repo not in self.installation.checkouts:
            return None
        path = worktree_path(
            self.installation.checkouts[unit.repo], unit.branch, self.installation.worktree_root
        )
        return path if path.is_dir() else None

    def unit_at(self, cwd: str | Path) -> StoredUnit | None:
        """The unit whose worktree `cwd` is, or lies in."""
        here = Path(cwd).resolve()
        for unit in self._units():
            tree = self.worktree(unit)
            if tree is not None and here.is_relative_to(tree.resolve()):
                return unit
        return None

    def running(self, unit: StoredUnit) -> bool:
        units = self._units()
        fresh = next((u for u in units if u.id == unit.id), unit)
        return effective_state(fresh, units) == "running"

    def claim(self, unit: StoredUnit, tab: str) -> bool:
        """Take the unit's lease for `tab`, and only then check that no step runs on the
        unit: a tick that started one in between is seen here, and one that comes after
        finds the lease. True when the lease is new."""
        from agent_build_kit.cli.pipeline import branch_is_held

        mine = f"tab:{tab}"
        had = self.leases.holder(unit.id) == mine
        if not self.leases.take(unit.id, mine):
            raise _conflict("another tab holds the lease")
        if self.running(unit) or (unit.branch and branch_is_held(self.installation, unit.branch)):
            if not had:
                self.leases.release(unit.id, mine)
            raise _conflict("a step is running on the unit")
        return not had

    def leased(self, unit: StoredUnit, tab: str, start: Callable[[], StreamingResponse]):
        """`start()` under the unit's lease, which a refused start gives back."""
        new = self.claim(unit, tab)
        try:
            return start()
        except HTTPException:
            if new:
                self.leases.release(unit.id, f"tab:{tab}")
            raise

    # --- who has a session ------------------------------------------------------------

    def busy(self, session: str) -> bool:
        return session in self._busy

    def holders(self, session: str, cwd: str = "", newest: bool = False) -> list[int]:
        return holding_pids(session, cwd=cwd, newest=newest)

    def claude_holders(self, session: str) -> list[int]:
        """Processes that have a Claude session open: one with its id in its arguments, or a
        `claude` working in the directory the session is the newest of."""
        seen: set[str] = set()
        for item in claude_sessions(claude_home()):
            first = item.cwd not in seen
            seen.add(item.cwd)
            if item.id == session:
                return self.holders(session, item.cwd, first)
        return self.holders(session)

    def session_holders(self, runtime: str, session: str) -> list[int]:
        return self.claude_holders(session) if runtime == CLAUDE else self.holders(session)

    # --- tabs -------------------------------------------------------------------------

    def _tab_closed(self, tab: str) -> threading.Event:
        return self._closed.setdefault(tab, threading.Event())

    def open_tab(self, tab: str) -> None:
        with self._lock:
            self._closing.discard(tab)
        self._tab_closed(tab).clear()

    def close_tab(self, tab: str) -> None:
        """The page is gone: its open requests are denied, and its leases go back to the
        tick once no turn it started is still running, so no agent is left editing a
        worktree the tick has taken back."""
        self._tab_closed(tab).set()
        with self._lock:
            if self._turns.get(tab):
                self._closing.add(tab)
                return
        self.leases.release_all(f"tab:{tab}")

    def _turn_ended(self, tab: str) -> None:
        with self._lock:
            self._turns[tab] -= 1
            last = self._turns[tab] == 0
            closing = last and tab in self._closing
            if closing:
                self._closing.discard(tab)
        if closing:
            self.leases.release_all(f"tab:{tab}")

    def shutdown(self) -> None:
        """The server is stopping: every open permission request is denied, so no turn is left
        waiting on a page that will not answer, and the pages' streams end."""
        self._stopping.set()

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    def answer(self, ask_id: str, option: str) -> None:
        try:
            done, box = self._asks[ask_id]
        except KeyError:
            raise HTTPException(status_code=404, detail="no such request") from None
        box[0] = option
        done.set()

    def _ask(self, tab: str, events: queue.Queue[Any], ask: PermissionAsk) -> str | None:
        """Show `ask` in the browser and wait for the answer; the page closing denies it."""
        ask_id = uuid.uuid4().hex
        done, box = threading.Event(), cast(list[str | None], [None])
        self._asks[ask_id] = (done, box)
        events.put(
            {
                "type": "CUSTOM",
                "name": "permission_request",
                "value": {
                    "id": ask_id,
                    "tool": ask.tool,
                    "input": ask.input,
                    "options": [o.model_dump() for o in ask.options],
                },
            }
        )
        closed = self._tab_closed(tab)
        try:
            while not done.wait(ANSWER_POLL_SECONDS):
                if closed.is_set() or self._stopping.is_set():
                    return None
            return box[0]
        finally:
            self._asks.pop(ask_id, None)

    # --- turns ------------------------------------------------------------------------

    def stream(
        self,
        runtime: Any,
        build: Callable[[dict[str, Any]], AgentRequest],
        *,
        tab: str,
        unit: StoredUnit | None,
        said: str,
        session: str = "",
        fallback: Callable[[dict[str, Any]], AgentRequest] | None = None,
    ) -> StreamingResponse:
        """Run the call `build` makes on a thread and stream its events as they arrive.
        `said` is what the person asked, which the unit's transcript keeps. A second turn
        on `session` while one runs is refused."""
        with self._lock:
            if session and session in self._busy:
                raise _conflict("a turn is already running on this session")
            owned = {session} if session else set()
            self._busy |= owned
            self._turns[tab] = self._turns.get(tab, 0) + 1
        events: queue.Queue[Any] = queue.Queue()
        encoder = AgUiEncoder(unit.id if unit else session or uuid.uuid4().hex, uuid.uuid4().hex)
        record = None
        if unit is not None:
            limits = self.installation.config.limits
            record = Transcript(
                self.transcripts,
                unit,
                node="chat",
                round=0,
                source="chat",
                started=datetime.now(UTC),
                result_limit=limits.transcript_result_chars,
                runs_kept=limits.transcript_runs_kept,
            )
        finished: list[bool] = []
        asked: list[bool] = []

        def keep_question(session_id: str) -> None:
            if record is not None and not asked:
                asked.append(True)
                record.record(TranscriptEvent(kind="user", session=session_id, text=said))

        def on_record(event: TranscriptEvent) -> None:
            if record is not None:
                record.record(event)
            if event.kind == "stop":
                finished.append(True)
            for made in encoder.encode(event):
                events.put(made)

        def on_session(session_id: str) -> None:
            with self._lock:
                self._busy.add(session_id)
                owned.add(session_id)
            keep_question(session_id)
            events.put({"type": "CUSTOM", "name": "session", "value": {"id": session_id}})

        callbacks = {
            "on_record": on_record,
            "on_session": on_session,
            "on_permission": lambda ask: self._ask(tab, events, ask),
        }

        def call(make: Callable[[dict[str, Any]], AgentRequest]) -> AgentResult:
            return runtime.run(make(callbacks))

        def work() -> None:
            for made in encoder.start():
                events.put(made)
            try:
                try:
                    result = call(build)
                except SessionUnavailable:
                    if fallback is None:
                        raise
                    events.put({"type": "CUSTOM", "name": "continued_as_new", "value": {}})
                    result = call(fallback)
                if finished:
                    tail = encoder.close()
                elif result.ok:
                    tail = encoder.finish("end_turn")
                else:
                    tail = encoder.fail(result.error)
            except Exception as exc:  # noqa: BLE001 — the browser is told what went wrong
                tail = encoder.close() if finished else encoder.fail(str(exc) or "error")
            try:
                for made in tail:
                    events.put(made)
            finally:
                with self._lock:
                    self._busy -= owned
                events.put(None)
                self._turn_ended(tab)

        threading.Thread(target=work, daemon=True).start()

        def body() -> Iterator[str]:
            while (item := events.get()) is not None:
                yield _sse(item)

        return StreamingResponse(body(), media_type="text/event-stream")

    def request(
        self,
        callbacks: dict[str, Any],
        prompt: str,
        cwd: Path,
        *,
        model: str | None = None,
        resume: str = "",
        fork: bool = False,
        policed: bool = True,
    ) -> AgentRequest:
        return AgentRequest(
            prompt=prompt,
            cwd=cwd,
            model=model or None,
            resume_session=resume,
            fork_session=fork,
            policy=ToolPolicy(specs_dir=self.installation.specs_dir) if policed else None,
            **callbacks,
        )

    # --- the sessions page ----------------------------------------------------------------

    def acp_sessions(self) -> dict[str, tuple[StoredUnit, list[TranscriptEvent]]]:
        """Sessions only the server's own transcripts know, by id: those of a runtime
        that keeps no file the page can read are taken to be ACP sessions."""
        known: dict[str, tuple[StoredUnit, list[TranscriptEvent]]] = {}
        for unit in self._units():
            for event in read_transcripts(self.transcripts, unit.id):
                if event.session:
                    known.setdefault(event.session, (unit, []))[1].append(event)
        return known

    def claude_file(self, session: str) -> Path | None:
        found = next((s for s in claude_sessions(claude_home()) if s.id == session), None)
        return found.path if found else None


def register(
    app: FastAPI,
    installation: Installation,
    *,
    units: Callable[[], list[StoredUnit]],
    recorded_session: Callable[[str], AgentSession | None],
) -> None:
    chat = Chat(installation, units=units, recorded_session=recorded_session)
    # The server's stop calls this before uvicorn waits on its open requests: a turn waiting
    # for an answer and a page's open stream are requests it would wait on for ever.
    app.state.stop_chat = chat.shutdown

    def agent_state(unit: StoredUnit, tab: str) -> dict[str, Any]:
        recorded = recorded_session(unit.id)
        holder = chat.leases.holder(unit.id)
        running = chat.running(unit)
        pids = chat.session_holders(recorded.runtime, recorded.session_id) if recorded else []
        mine = f"tab:{tab}"
        state = "attached" if holder else "paused"
        if running:
            state, enabled, reason = (
                "streaming",
                False,
                "A step is running; its work is streamed here and takes no input.",
            )
        elif holder is not None and holder != mine:
            enabled, reason = False, f"{holder} is chatting with this unit; it holds the lease."
        elif recorded is None:
            enabled, reason = False, "No agent session was recorded for this unit."
        elif chat.busy(recorded.session_id):
            enabled, reason = False, "A turn is already running on this session."
        elif pids:
            enabled, reason = False, f"Process {pids[0]} holds this session; it is read-only here."
        else:
            enabled, reason = True, ""
        return {
            "session": {
                "id": recorded.session_id,
                "runtime": recorded.runtime,
                "model": recorded.model,
            }
            if recorded
            else None,
            "state": state,
            "composer": {"enabled": enabled, "reason": reason},
            "attached_by": holder,
        }

    @app.get("/api/units/{change}/{number}/agent")
    def agent(change: str, number: str, tab: str = "") -> dict[str, Any]:
        return agent_state(chat.unit(change, number), tab)

    @app.get("/api/tabs/events")
    async def tab_events(request: Request, tab: str) -> StreamingResponse:
        """A page that is not a unit's agent tab holds its tab open with this stream; its
        closing is the page closing, as for the agent tab's own."""
        gone = asyncio.Event()

        async def watch() -> None:
            while (await request.receive())["type"] != "http.disconnect":
                pass
            gone.set()

        async def body() -> AsyncIterator[str]:
            chat.open_tab(tab)
            watcher = asyncio.create_task(watch())
            try:
                yield ": open\n\n"
                while not gone.is_set() and not chat.stopping:
                    await asyncio.sleep(POLL_SECONDS)
            finally:
                watcher.cancel()
                chat.close_tab(tab)

        return StreamingResponse(body(), media_type="text/event-stream")

    @app.get("/api/units/{change}/{number}/agent/events")
    async def agent_events(
        request: Request, change: str, number: str, tab: str = ""
    ) -> StreamingResponse:
        unit = chat.unit(change, number)

        gone = asyncio.Event()

        async def watch() -> None:
            # The page closing is the connection closing, which only the receive channel tells.
            while (await request.receive())["type"] != "http.disconnect":
                pass
            gone.set()

        async def body() -> AsyncIterator[str]:
            chat.open_tab(tab)
            watcher = asyncio.create_task(watch())
            try:
                # How far each file has been read: a position per file, since a new run
                # removes the oldest files and the events of the rest must not shift.
                read: dict[str, int] = {}
                seen: list[TranscriptEvent] = []
                for path in unit_transcript_files(chat.transcripts, unit.id):
                    events, read[path.name] = read_file_events(path)
                    seen += events
                yield _sse(messages_snapshot(seen))
                runs: dict[str, AgUiEncoder] = {}
                open_run: str | None = None
                while not gone.is_set() and not chat.stopping:
                    await asyncio.sleep(POLL_SECONDS)
                    for path in unit_transcript_files(chat.transcripts, unit.id):
                        events, read[path.name] = read_file_events(path, read.get(path.name, 0))
                        live = [e for e in events if e.source == "build"]
                        if not live:
                            continue
                        if path.name not in runs:
                            if open_run is not None:
                                for made in runs[open_run].fail("the run ended without finishing"):
                                    yield _sse(made)
                            runs[path.name] = AgUiEncoder(unit.id, path.stem)
                            open_run = path.name
                            for made in runs[path.name].start():
                                yield _sse(made)
                        for event in live:
                            for made in runs[path.name].encode(event):
                                yield _sse(made)
                            if event.kind == "stop" and open_run == path.name:
                                open_run = None
            finally:
                watcher.cancel()
                chat.close_tab(tab)

        return StreamingResponse(body(), media_type="text/event-stream")

    @app.post("/api/units/{change}/{number}/chat")
    def unit_chat(change: str, number: str, body: Turn) -> StreamingResponse:
        unit = chat.unit(change, number)
        state = agent_state(unit, body.tab)
        if not state["composer"]["enabled"]:
            raise _conflict(state["composer"]["reason"])
        recorded = recorded_session(unit.id)
        assert recorded is not None
        cwd = chat.worktree(unit)
        if cwd is None:
            raise _conflict("the unit has no worktree")
        try:
            runtime = runtimes.get(recorded.runtime)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        prompt = with_attachments(body.prompt, body.attachments)
        return chat.leased(
            unit,
            body.tab,
            lambda: chat.stream(
                runtime,
                lambda cb: chat.request(
                    cb, prompt, cwd, model=recorded.model, resume=recorded.session_id
                ),
                tab=body.tab,
                unit=unit,
                said=prompt,
                session=recorded.session_id,
            ),
        )

    @app.delete("/api/units/{change}/{number}/lease")
    def release(change: str, number: str, tab: str = "") -> Response:
        chat.leases.release(chat.unit(change, number).id, f"tab:{tab}")
        return Response(status_code=204)

    @app.post("/api/permissions/{ask_id}")
    def permission(ask_id: str, body: Answer) -> Response:
        chat.answer(ask_id, body.option)
        return Response(status_code=204)

    # --- sessions --------------------------------------------------------------------------

    @app.get("/api/sessions")
    def sessions() -> dict[str, Any]:
        listed: dict[str, dict[str, Any]] = {}
        newest: set[str] = set()
        seen: set[str] = set()
        found = claude_sessions(claude_home())
        for item in found:
            if item.cwd not in seen:
                seen.add(item.cwd)
                newest.add(item.id)
        for item in found:
            unit = chat.unit_at(item.cwd) if item.cwd else None
            listed[item.id] = {
                "id": item.id,
                "runtime": CLAUDE,
                "cwd": item.cwd,
                "title": item.title,
                "updated": item.updated,
                "held": bool(chat.holders(item.id, item.cwd, item.id in newest)),
                "loadable": True,
                "unit": unit.id if unit else None,
            }
        for session, (unit, events) in chat.acp_sessions().items():
            if session in listed:
                listed[session]["unit"] = unit.id
                continue
            tree = chat.worktree(unit)
            made = recorded_session(unit.id)
            listed[session] = {
                "id": session,
                # The runtime that ran the unit's turns, which wrote these transcripts.
                "runtime": made.runtime if made else ACP,
                "cwd": str(tree) if tree else "",
                "title": next(
                    (e.text.strip().splitlines()[0] for e in events if e.text.strip()), ""
                ),
                "updated": events[-1].at,
                "held": bool(chat.holders(session)),
                "loadable": None,
                "unit": unit.id,
            }
        return {"sessions": list(listed.values())}

    def history(runtime: str, session: str) -> tuple[list[dict[str, Any]], bool]:
        """The session's events, and whether they are the server's own record."""
        if runtime == CLAUDE:
            path = chat.claude_file(session)
            if path is not None:
                return claude_events(path), False
        known = chat.acp_sessions().get(session)
        if known is None:
            raise HTTPException(status_code=404, detail=f"no session {session}")
        return [e.model_dump() for e in known[1]], True

    def resumable(session: str) -> bool:
        """Whether the agent would resume this ACP session in place: it advertises resume and
        list, and lists the id for the session's directory."""
        unit = chat.acp_sessions()[session][0]
        cwd = chat.worktree(unit) or installation.root
        can = getattr(runtimes.get(ACP), "can_resume_session", None)
        return bool(can is not None and can(session, cwd))

    @app.get("/api/sessions/{runtime}/{session}")
    def one_session(runtime: str, session: str) -> dict[str, Any]:
        events, recorded = history(runtime, session)
        pids = chat.session_holders(runtime, session)
        if chat.busy(session):
            read_only, reason = True, "A turn is running on this session."
            actions: list[str] = []
        elif pids:
            read_only = True
            reason = f"Process {pids[0]} holds this session; it is read-only here."
            actions = ["fork"] if runtime == CLAUDE else ["continue_as_new"]
        elif runtime == ACP and not resumable(session):
            read_only = True
            reason = (
                "The agent cannot resume this session: it is shown read-only and can only be "
                "continued as a new session seeded with this history."
            )
            actions = ["continue_as_new"]
        else:
            read_only, reason = False, ""
            actions = ["continue", "fork"] if runtime == CLAUDE else ["continue"]
        return {
            "id": session,
            "runtime": runtime,
            "events": events,
            "recorded": recorded,
            "tool_calls_available": True,
            "read_only": read_only,
            "reason": reason,
            "actions": actions,
        }

    def claude_turn(session: str, body: Turn, *, fork: bool) -> StreamingResponse:
        found = next((s for s in claude_sessions(claude_home()) if s.id == session), None)
        if found is None:
            raise HTTPException(status_code=404, detail=f"no session {session}")
        cwd = Path(found.cwd) if found.cwd and Path(found.cwd).is_dir() else installation.root
        # A session in a unit's worktree is the unit's, and goes by the unit's rules: not
        # while a step runs, under the lease, and with the pipeline's tool policy.
        unit = chat.unit_at(cwd)
        prompt = with_attachments(body.prompt, body.attachments)
        recorded = recorded_session(unit.id) if unit is not None else None
        model = recorded.model if recorded and recorded.session_id == session else None

        def start() -> StreamingResponse:
            return chat.stream(
                runtimes.get(CLAUDE),
                lambda cb: chat.request(
                    cb,
                    prompt,
                    cwd,
                    model=model,
                    resume=session,
                    fork=fork,
                    policed=unit is not None,
                ),
                tab=body.tab,
                unit=unit,
                said=prompt,
                session="" if fork else session,
            )

        return chat.leased(unit, body.tab, start) if unit is not None else start()

    def acp_turn(session: str, body: Turn, *, seeded: bool) -> StreamingResponse:
        events, _ = history(ACP, session)
        unit = chat.acp_sessions()[session][0]
        cwd = chat.worktree(unit) or installation.root
        prompt = with_attachments(body.prompt, body.attachments)
        recorded = recorded_session(unit.id)
        model = recorded.model if recorded and recorded.session_id == session else None
        fresh = lambda cb: chat.request(cb, _seed(events, prompt), cwd, model=model)  # noqa: E731
        return chat.leased(
            unit,
            body.tab,
            lambda: chat.stream(
                runtimes.get(ACP),
                fresh
                if seeded
                else lambda cb: chat.request(cb, prompt, cwd, model=model, resume=session),
                tab=body.tab,
                unit=unit,
                said=prompt,
                session=session,
                fallback=fresh,
            ),
        )

    @app.post("/api/sessions/{runtime}/{session}/continue")
    def continue_session(runtime: str, session: str, body: Turn) -> StreamingResponse:
        if chat.busy(session):
            raise _conflict("a turn is already running on this session")
        held = bool(chat.session_holders(runtime, session))
        if runtime == CLAUDE:
            return claude_turn(session, body, fork=held)
        if runtime == ACP:
            return acp_turn(session, body, seeded=held)
        raise HTTPException(status_code=404, detail=f"no runtime {runtime}")

    @app.post("/api/sessions/{runtime}/{session}/fork")
    def fork_session(runtime: str, session: str, body: Turn) -> StreamingResponse:
        if runtime == CLAUDE:
            return claude_turn(session, body, fork=True)
        if runtime == ACP:
            return acp_turn(session, body, seeded=True)
        raise HTTPException(status_code=404, detail=f"no runtime {runtime}")

    @app.post("/api/sessions")
    def new_session(body: NewSession) -> StreamingResponse:
        try:
            runtime = runtimes.get(body.runtime)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        unit = None
        if body.unit:
            change, _, number = body.unit.partition("/")
            unit = chat.unit(change, number)
            tree = chat.worktree(unit)
            if tree is None:
                raise _conflict("the unit has no worktree")
            cwd: Path = tree
        elif body.repo in installation.checkouts:
            cwd = installation.checkouts[body.repo]
        else:
            raise HTTPException(status_code=400, detail="name a unit or a repo")
        prompt = with_attachments(body.prompt, body.attachments)

        def start() -> StreamingResponse:
            return chat.stream(
                runtime,
                lambda cb: chat.request(cb, prompt, cwd, model=body.model),
                tab=body.tab,
                unit=unit,
                said=prompt,
            )

        return chat.leased(unit, body.tab, start) if unit is not None else start()
