import { useCallback, useEffect, useReducer, useState } from "react";
import type { ReactElement } from "react";

import { EMPTY, asked, readEvents, reduce } from "./agui";
import type { AguiEvent, Conversation } from "./agui";
import { Composer } from "./composer";
import type { Turn } from "./composer";
import { useApi } from "./useApi";

interface AgentState {
  session: { id: string; runtime: string; model: string } | null;
  state: "streaming" | "paused" | "attached";
  composer: { enabled: boolean; reason: string };
  attached_by: string | null;
}

type Action = { event: AguiEvent } | { asked: string };

function step(conversation: Conversation, action: Action): Conversation {
  return "event" in action ? reduce(conversation, action.event) : asked(conversation, action.asked);
}

/** A random id for this page, which the server holds the lease and open requests against. */
function newTab(): string {
  return Math.random().toString(36).slice(2, 12);
}

/** What was said and done, in order. */
export function ConversationView({ conversation }: { conversation: Conversation }): ReactElement {
  return (
    <ol aria-label="Conversation">
      {conversation.items.map((item) =>
        item.kind === "message" ? (
          <li key={item.id} data-role={item.role}>
            <strong>{item.role}:</strong> {item.text}
          </li>
        ) : (
          <li key={item.id} data-role="tool">
            <strong>{item.name}</strong> <code>{item.args}</code>
            {item.result !== null && <pre>{item.result}</pre>}
          </li>
        ),
      )}
    </ol>
  );
}

/** A permission request from a turn, with the options the server offers. */
export function Permission({
  conversation,
  onAnswer,
}: {
  conversation: Conversation;
  onAnswer: (id: string, option: string) => void;
}): ReactElement | null {
  const ask = conversation.ask;
  if (!ask) return null;
  return (
    <section role="alert" aria-label="Permission request">
      <p>
        The agent asks to run <code>{ask.tool}</code>
      </p>
      {ask.options.map((option) => (
        <button key={option.id} onClick={() => onAnswer(ask.id, option.id)}>
          {option.name}
        </button>
      ))}
    </section>
  );
}

/** Read a turn's reply into `dispatch`; an unreadable reply is an error line. */
export async function follow(
  response: Response,
  dispatch: (action: Action) => void,
): Promise<void> {
  if (!response.ok) {
    const detail = ((await response.json().catch(() => ({}))) as { detail?: string }).detail;
    dispatch({
      event: { type: "RUN_ERROR", message: detail ?? `the server answered ${response.status}` },
    });
    return;
  }
  for await (const event of readEvents(response)) dispatch({ event });
}

export async function answerPermission(id: string, option: string): Promise<void> {
  await fetch(`/api/permissions/${id}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ option }),
  });
}

/** Hold `tab` open for as long as the calling page is shown: the server treats the stream's
 * closing as the page closing, returning the units the tab holds and denying its requests. */
export function usePresence(tab: string): void {
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`/api/tabs/events?tab=${tab}`, {
          signal: controller.signal,
        });
        if (response.ok) await follow(response, () => undefined);
      } catch {
        // Aborted with the page, or the server went away.
      }
    })();
    return () => controller.abort();
  }, [tab]);
}

/** The agent tab of a unit: its running step streamed, and a chat once the step has ended. */
export function AgentTab({ name }: { name: string }): ReactElement {
  const [tab] = useState(newTab);
  const [version, setVersion] = useState(0);
  const [conversation, dispatch] = useReducer(step, EMPTY);
  const state = useApi<AgentState>(`/api/units/${name}/agent?tab=${tab}&v=${version}`);

  useEffect(() => {
    // The page open is the tab: closing the stream gives its lease back.
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`/api/units/${name}/agent/events?tab=${tab}`, {
          signal: controller.signal,
        });
        if (response.ok) {
          await follow(response, (action) => {
            dispatch(action);
            // A step that ends changes what the composer may do: ask the server again.
            if ("event" in action && ["RUN_FINISHED", "RUN_ERROR"].includes(action.event.type)) {
              setVersion((v) => v + 1);
            }
          });
        }
      } catch {
        // Aborted with the page, or the server went away.
      }
    })();
    return () => controller.abort();
  }, [name, tab]);

  const send = useCallback(
    async (turn: Turn) => {
      dispatch({ asked: turn.prompt });
      const response = await fetch(`/api/units/${name}/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ tab, ...turn }),
      });
      await follow(response, dispatch);
      setVersion((v) => v + 1);
    },
    [name, tab],
  );

  const release = useCallback(async () => {
    await fetch(`/api/units/${name}/lease?tab=${tab}`, { method: "DELETE" });
    setVersion((v) => v + 1);
  }, [name, tab]);

  const agent = state && "data" in state ? state.data : null;
  return (
    <section aria-label="Agent">
      {state && "error" in state && <p role="alert">{state.error}</p>}
      {agent && (
        <p>
          {agent.state === "streaming" && "A step is running."}
          {agent.state === "paused" && "The step has ended."}
          {agent.state === "attached" &&
            `Attached: ${agent.attached_by ?? "a tab"} holds the unit.`}
        </p>
      )}
      <ConversationView conversation={conversation} />
      {conversation.error && <p role="alert">{conversation.error}</p>}
      <Permission
        conversation={conversation}
        onAnswer={(id, option) => void answerPermission(id, option)}
      />
      {agent?.attached_by === `tab:${tab}` && (
        <button onClick={() => void release()}>Release the unit to the pipeline</button>
      )}
      {agent && (
        <Composer
          attachments={[]}
          disabledReason={agent.composer.enabled ? undefined : agent.composer.reason}
          onSend={(turn) => void send(turn)}
        />
      )}
    </section>
  );
}
