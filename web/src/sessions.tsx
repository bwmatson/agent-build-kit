import { useCallback, useReducer, useState } from "react";
import type { ReactElement } from "react";

import { Permission, answerPermission, follow, usePresence } from "./agent";
import { EMPTY, asked, reduce } from "./agui";
import type { AguiEvent, Conversation } from "./agui";
import { Composer } from "./composer";
import type { Turn } from "./composer";
import { ConversationView } from "./agent";
import type { UnitSummary } from "./api";
import { useApi } from "./useApi";

interface SessionInfo {
  id: string;
  runtime: string;
  cwd: string;
  title: string;
  updated: string;
  held: boolean;
  loadable: boolean | null;
  unit: string | null;
}

interface SessionEvent {
  kind: string;
  role?: string;
  text?: string;
  tool?: string;
  input?: Record<string, unknown>;
}

interface SessionDetail {
  id: string;
  runtime: string;
  events: SessionEvent[];
  recorded: boolean;
  tool_calls_available: boolean;
  read_only: boolean;
  reason: string;
  actions: ("continue" | "fork" | "continue_as_new")[];
}

const ACTIONS = {
  continue: { label: "Continue", path: "continue" },
  fork: { label: "Fork and continue", path: "fork" },
  continue_as_new: { label: "Continue as a new session", path: "continue" },
} as const;

type Action = { event: AguiEvent } | { asked: string };

function step(conversation: Conversation, action: Action): Conversation {
  return "event" in action ? reduce(conversation, action.event) : asked(conversation, action.asked);
}

function newTab(): string {
  return Math.random().toString(36).slice(2, 12);
}

function History({ events }: { events: SessionEvent[] }): ReactElement {
  return (
    <ol aria-label="History">
      {events
        .filter((event) => ["text", "user", "tool_call"].includes(event.kind))
        .map((event, index) => (
          <li key={index}>
            {event.kind === "tool_call" ? (
              <>
                <strong>{event.tool}</strong> <code>{JSON.stringify(event.input)}</code>
              </>
            ) : (
              <>
                <strong>{event.role ?? event.kind}:</strong> {event.text}
              </>
            )}
          </li>
        ))}
    </ol>
  );
}

/** A reply being streamed: what was said, a failure, and any request to answer. */
function Reply({ conversation }: { conversation: Conversation }): ReactElement {
  return (
    <>
      <ConversationView conversation={conversation} />
      {conversation.error && <p role="alert">{conversation.error}</p>}
      <Permission
        conversation={conversation}
        onAnswer={(id, option) => void answerPermission(id, option)}
      />
    </>
  );
}

/** The unit a turn took, with the way to give it back before the page closes. */
function Attached({ unit, tab, version }: { unit: string; tab: string; version: number }) {
  const [released, setReleased] = useState(0);
  const state = useApi<{ attached_by: string | null }>(
    `/api/units/${unit}/agent?tab=${tab}&v=${version}.${released}`,
  );
  if (!state || !("data" in state) || state.data.attached_by !== `tab:${tab}`) return null;
  return (
    <button
      onClick={() => {
        void fetch(`/api/units/${unit}/lease?tab=${tab}`, { method: "DELETE" }).then(() =>
          setReleased((n) => n + 1),
        );
      }}
    >
      Release the unit to the pipeline
    </button>
  );
}

function SessionView({ session, tab }: { session: SessionInfo; tab: string }): ReactElement {
  const [version, setVersion] = useState(0);
  const [chosen, setChosen] = useState<string | null>(null);
  const [reply, dispatch] = useReducer(step, EMPTY);
  const detail = useApi<SessionDetail>(`/api/sessions/${session.runtime}/${session.id}`);
  const data = detail && "data" in detail ? detail.data : null;
  const action = data ? (chosen ?? data.actions[0]) : undefined;

  const send = useCallback(
    async (turn: Turn) => {
      if (!action) return;
      dispatch({ asked: turn.prompt });
      const path = ACTIONS[action as keyof typeof ACTIONS].path;
      const response = await fetch(`/api/sessions/${session.runtime}/${session.id}/${path}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ tab, ...turn }),
      });
      await follow(response, dispatch);
      setVersion((v) => v + 1);
    },
    [action, session, tab],
  );

  return (
    <section aria-label="Session">
      <h2>{session.title || session.id}</h2>
      {detail && "error" in detail && <p role="alert">{detail.error}</p>}
      {data && (
        <>
          {data.read_only && <p role="status">Read-only: {data.reason}</p>}
          {!data.recorded && !data.tool_calls_available && (
            <p>Tool calls are not available for this session.</p>
          )}
          <History events={data.events} />
          <fieldset>
            <legend>How to go on</legend>
            {data.actions.map((name) => (
              <label key={name}>
                <input
                  type="radio"
                  name="action"
                  checked={name === action}
                  onChange={() => setChosen(name)}
                />
                {ACTIONS[name].label}
              </label>
            ))}
          </fieldset>
          <Reply conversation={reply} />
          {session.unit && <Attached unit={session.unit} tab={tab} version={version} />}
          <Composer
            attachments={[]}
            disabledReason={action ? undefined : "This session cannot be continued from here."}
            onSend={(turn) => void send(turn)}
          />
        </>
      )}
    </section>
  );
}

const RUNTIMES = ["claude_code", "acp"];

/** Start a session for a unit, in its worktree, or for a repo, on a chosen runtime and model. */
function NewSession({ tab }: { tab: string }): ReactElement {
  const pipeline = useApi<{ units: UnitSummary[] }>("/api/pipeline");
  const units = pipeline && "data" in pipeline ? pipeline.data.units : [];
  const repos = [...new Set(units.map((u) => u.repo))];
  const [runtime, setRuntime] = useState(RUNTIMES[0]);
  const [model, setModel] = useState("");
  const [target, setTarget] = useState<"unit" | "repo">("unit");
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [reply, dispatch] = useReducer(step, EMPTY);
  const options = target === "unit" ? units.map((u) => u.id) : repos;
  const picked = choice[target] ?? options[0] ?? "";

  const send = useCallback(
    async (turn: Turn) => {
      dispatch({ asked: turn.prompt });
      const response = await fetch("/api/sessions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ tab, runtime, model, [target]: picked, ...turn }),
      });
      await follow(response, dispatch);
    },
    [tab, runtime, model, target, picked],
  );

  return (
    <section aria-label="New session">
      <h2>New session</h2>
      <label>
        Runtime
        <select value={runtime} onChange={(e) => setRuntime(e.target.value)}>
          {RUNTIMES.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <label>
        Model
        <input value={model} onChange={(e) => setModel(e.target.value)} />
      </label>
      <label>
        For
        <select value={target} onChange={(e) => setTarget(e.target.value as "unit" | "repo")}>
          <option value="unit">A unit&apos;s worktree</option>
          <option value="repo">A repo</option>
        </select>
      </label>
      <label>
        {target === "unit" ? "Unit" : "Repo"}
        <select value={picked} onChange={(e) => setChoice({ ...choice, [target]: e.target.value })}>
          {options.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <Reply conversation={reply} />
      {target === "unit" && picked && (
        <Attached unit={picked} tab={tab} version={reply.items.length} />
      )}
      <Composer
        attachments={[]}
        disabledReason={picked ? undefined : "Nothing to start a session in yet."}
        onSend={(turn) => void send(turn)}
      />
    </section>
  );
}

/** The sessions started anywhere: in an editor, a command line, or here. */
export function SessionsPage(): ReactElement {
  const listed = useApi<{ sessions: SessionInfo[] }>("/api/sessions");
  const [open, setOpen] = useState<SessionInfo | null>(null);
  const [creating, setCreating] = useState(false);
  // This page is one tab for as long as it is shown, whichever session or form it is on.
  const [tab] = useState(newTab);
  usePresence(tab);
  return (
    <main>
      <h1>Sessions</h1>
      {listed && "error" in listed && <p role="alert">{listed.error}</p>}
      {listed && "data" in listed && (
        <ul aria-label="Sessions">
          {listed.data.sessions.map((session) => (
            <li key={session.id}>
              <button onClick={() => setOpen(session)}>{session.title || session.id}</button>{" "}
              <span>{session.runtime}</span> <code>{session.cwd}</code>
              {session.unit && <span> unit {session.unit}</span>}
              {session.held && <strong> held by a running process</strong>}
            </li>
          ))}
        </ul>
      )}
      <button onClick={() => setCreating(!creating)} aria-expanded={creating}>
        New session
      </button>
      {creating && <NewSession tab={tab} />}
      {open && <SessionView key={open.id} session={open} tab={tab} />}
    </main>
  );
}
