// A stand-in for `abk serve` at the HTTP boundary: `fetch` answers with the JSON
// the server sent when these were recorded (src/test/recorded), nothing in between.
import { vi } from "vitest";

import agentFeature2 from "./recorded/agent-feature-2.json";
import agentFeature7 from "./recorded/agent-feature-7.json";
import chatFeature2 from "./recorded/chat-feature-2.sse?raw";
import chatPermission from "./recorded/chat-permission.sse?raw";
import eventsFeature2 from "./recorded/events-feature-2.sse?raw";
import pipeline from "./recorded/pipeline.json";
import runImplement from "./recorded/run-implement.json";
import runTests from "./recorded/run-tests.json";
import runsFeature7 from "./recorded/runs-feature-7.json";
import sessionAcp from "./recorded/session-acp-unloadable.json";
import sessionHeld from "./recorded/session-held.json";
import sessionIdle from "./recorded/session-idle.json";
import sessions from "./recorded/sessions.json";
import unit1 from "./recorded/unit-feature-1.json";
import unit2 from "./recorded/unit-feature-2.json";
import unit3 from "./recorded/unit-feature-3.json";
import unit4 from "./recorded/unit-feature-4.json";
import unit5 from "./recorded/unit-feature-5.json";
import unit6 from "./recorded/unit-feature-6.json";
import unit7 from "./recorded/unit-feature-7.json";
import unit8 from "./recorded/unit-feature-8.json";
import unit9 from "./recorded/unit-feature-9.json";
import usageNode from "./recorded/usage-node.json";
import usageUnit from "./recorded/usage-unit.json";

export const UNITS = {
  "feature/1": unit1,
  "feature/2": unit2,
  "feature/3": unit3,
  "feature/4": unit4,
  "feature/5": unit5,
  "feature/6": unit6,
  "feature/7": unit7,
  "feature/8": unit8,
  "feature/9": unit9,
} as const;

export const SESSIONS = sessions.sessions;
export const HELD_SESSION = sessionHeld.id;
export const IDLE_SESSION = sessionIdle.id;
export const UNLOADABLE_SESSION = sessionAcp.id;

/** A server-sent-events body, as the server sends it. */
export function stream(body: string): Response {
  return new Response(body, { headers: { "content-type": "text/event-stream" } });
}

export const CHAT = chatFeature2;
export const CHAT_WITH_PERMISSION = chatPermission;

export const RUN_TESTS = runsFeature7.runs[0].name;
export const RUN_IMPLEMENT = runsFeature7.runs[1].name;

/** A body to send as JSON, or a whole `Response` (to answer an error). */
type Answer = unknown | ((url: URL, init?: RequestInit) => unknown);

export interface Api {
  /** Every request path (with its query) the page has made, in order. */
  requests: string[];
  /** Every request with its method and JSON body, in order. */
  sent: { method: string; path: string; body: unknown }[];
  /** Answer `path` (no query) with `answer` from now on. */
  answer(path: string, answer: Answer): void;
}

/** Install a `fetch` that answers the recorded API; anything else is a 404. */
export function recordedApi(): Api {
  const answers = new Map<string, Answer>([
    ["/api/pipeline", pipeline],
    ["/api/units/feature/2/agent", agentFeature2],
    ["/api/units/feature/7/agent", agentFeature7],
    ["/api/units/feature/2/agent/events", () => stream(eventsFeature2)],
    ["/api/tabs/events", () => stream(": open\n\n")],
    ["/api/sessions", sessions],
    [`/api/sessions/acp/${sessionAcp.id}`, sessionAcp],
    [`/api/sessions/claude_code/${sessionHeld.id}`, sessionHeld],
    [`/api/sessions/claude_code/${sessionIdle.id}`, sessionIdle],
    ["/api/units/feature/7/logs", runsFeature7],
    [`/api/units/feature/7/logs/${RUN_TESTS}`, runTests],
    [`/api/units/feature/7/logs/${RUN_IMPLEMENT}`, runImplement],
    ["/api/usage", (url: URL) => (url.searchParams.get("by") === "node" ? usageNode : usageUnit)],
  ]);
  for (const [id, body] of Object.entries(UNITS)) {
    answers.set(`/api/units/${id}`, body);
  }
  const api: Api = {
    requests: [],
    sent: [],
    answer: (path, answer) => void answers.set(path, answer),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://127.0.0.1:8765");
      api.requests.push(url.pathname + url.search);
      api.sent.push({
        method: init?.method ?? "GET",
        path: url.pathname,
        body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      });
      const answer = answers.get(url.pathname);
      if (answer === undefined) {
        return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
      }
      const body = typeof answer === "function" ? answer(url, init) : answer;
      if (body instanceof Response) return body;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  return api;
}
