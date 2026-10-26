# Design

## Shape

One Python process (`abk serve`, FastAPI on uvicorn, bound to 127.0.0.1) serves a REST and
server-sent-events API and the built UI. The UI is a React 19, Vite, Tailwind 4 single-page app using
react-router, recharts and CopilotKit's v2 client, laid out as a conventional AG-UI chat front end is: a list on the
left, a header, a centre outlet and a chat panel on the right, with the explicit thread id and key on
the chat component. It is built when the package is built and shipped as static files.

The server is Python, in the framework, because its readers are library calls: the unit store, the
usage report builder, the state vocabulary and the checkpointer with its allowlisted serialisation.

Readers use a bare `UnitStore` (no write hooks), read the checkpoint database read-only, read the
usage ledger by line and tail run logs by byte offset. Actions are the opposite: the CLI's own
functions, under the store's lock, with the real hooks. Approve has no CLI function today, so it gets
one, `approve_unit`, and `abk approve <unit>` is its command: it records an `approved` decision for the
unit's current round in the review store, with the head of the unit's pull request, and never merges,
pushes or votes on the host.

## Addresses and names

Units are addressed by their name, `change/N`: `/units/<change>/<n>` in the UI and
`/api/units/<change>/<n>` in the API. No number or generated id appears in a URL, a log line or an
action record.

## Status, cause and history

A unit's page shows its effective state and cause from the state vocabulary, never derived from note
text; the history is drawn as a timeline of `{state, at, cause, note}`; dependencies and merge gates are
listed with their own state. Review rounds and the next node come from the checkpoint through the
position helper, which runs nothing.

## Logs

Run logs are append-and-close files; the tailer polls by byte offset, survives the pruning of old
runs, treats a missing `outcome:` line as live, and converts the host-local clock in each line to UTC
from the header's start time. The journal's slice for a unit is filtered by the unit prefix.

The agent's words and tool commands are cut to one line before they reach either log today. The unit
log keeps them whole: newlines become indented continuation lines, so the file stays parsable by
line and older logs still parse. The journal keeps the one-line form. Until the unit log is
whole, the logs tab shows the full text from the unit's transcript.

## Usage

Usage is the report builder's output unchanged, so the CLI and the UI cannot disagree; per-unit
tables are the builder run for that unit under each grouping.

## Metrics

Two sources behind one interface. With Prometheus and Tempo reachable the server runs the queries
(delta-temporality data, so windowed sums, not rates) and a trace search; otherwise it derives the
same figures from local files. Local derivation is exact for tokens, cost, turns, node and wait
durations and unit counts; the remaining gaps (tick duration, review rounds after a thread ends,
pauses, check failures beyond the kept logs) are closed by appending small records at the existing
emit sites to a local file, exempt from the roll-up at archive. The page shows which source is
active, lists every metric from a catalogue generated from the telemetry module's instruments, and
links to the dashboard.

## Sessions and chat

A unit's agent session is the latest recorded session for its implement or rework node. The Claude
runtime already records it at start; the ACP runtime must too, and resume it where the agent
supports loading a session.

Interaction rules:
1. A step that is running is streamed read-only. There is no take-over of a live session.
2. When the step has ended (in review, held, failed, usage pause, between nodes) the composer
   enables. The first turn takes a lease on the unit, the same lease the tick respects, so no step
   starts while someone is chatting; releasing it, or the page closing, returns the unit to the tick,
   which resumes from the recorded node.
3. A new session can be started, as an editor does, for a unit (in its worktree), for a repo or for the
   planning repo.
4. A session started elsewhere (an editor, a command line, another front end) is listed and continued
   here: in place when no process holds it, by resuming its id (Claude) or loading it (an ACP agent
   that can). A session a process is driving is read-only here and is continued as a fork. Two writers on one transcript interleave it and leave the editor's in-memory context
   stale, so writing to it is refused while that process is live.
5. A permission request from a turn is shown in the browser and waits; closing the page denies it.
   Chat never widens a unit's allowed tools.

What a turn may change — files in the worktree, uncommitted until the user commits — and how a commit
enters the pipeline is the separate change `ui-chat-editing`; this change provides the lease, the
bridge and the recorded history it builds on.

A turn can carry attachments — a file, a line range, the diff hunk and the selected text — which are
put into the prompt as editors put their selection into theirs, and shown in the composer as chips that
can be removed first.

## Recorded history

The runtimes cannot be relied on to show a session back: Claude keeps a transcript in an internal
format that changes between versions, and an ACP session load replays text only. The server already
receives every event as it streams, so each run, and each chat turn made through the server, is written
to a transcript for its unit: one event per line, append-and-close like the run log, with the time,
unit, node, round, session id, source (build or chat) and a kind (text, reasoning, tool call, tool
result, plan, usage, permission, stop), whole, with tool results cut at a configured size and marked.
The agent tab replays one continuous history across build runs and chat turns from it. Only the most
recent runs per unit are kept, they go with the run logs at archive, and they stay on the machine.
A session that was not recorded is shown from its runtime's own history, saying where tool calls are
unavailable. The logs tab keeps reading the run log, whose agent words are whole.

The bridge from Claude and ACP messages to AG-UI events is part of this package. It maps messages,
reasoning, tool calls and results, plan and usage updates and stop reasons to the AG-UI event set, and
replays history as a messages snapshot on load.

## Safety

Loopback only; an optional shared key if ever bound wider. Logs, feedback and review text contain
command output and do not leave the machine. The metric stores are unauthenticated, so only the
server talks to them.

## Decisions pending

- Whether CopilotKit's `HttpAgent` can drive the Python endpoint directly, or a minimal Node runtime
  is needed (settled by a spike in the session bridge group).
- Whether an ACP agent's own session database may be read directly for tool history after a session load
  (it replays text only), or the replay is enough.
- The port, and whether the service starts with the tick timer or on demand.
