// The browser's end of the AG-UI streams `abk serve` sends: a small client that reads the
// server-sent events and folds them into what the agent tab shows.
//
// Spike (task 8.8): `@ag-ui/client`'s `HttpAgent` posts one `RunAgentInput` to a single url
// and reads that one run's events back. The server here has a persistent per-tab stream (a
// GET that outlives runs, carrying a snapshot and then every step), a turn body of its own
// (`tab`, `prompt`, `attachments`) and a lease to release, none of which `HttpAgent` models;
// driving it would need a `requestInit` override for the turns and a second client for the
// tab stream, plus rxjs and zod in the bundle, and a Node runtime only if CopilotKit's React
// components were used. The streams are valid AG-UI (the server's tests check every event
// against the protocol's own models), so adopting `@ag-ui/client` later is a change in this
// file alone. Until then, this client is enough.

export interface AguiEvent {
  type: string;
  [key: string]: unknown;
}

/** The events of a server-sent-events response, as they arrive. */
export async function* readEvents(response: Response): AsyncGenerator<AguiEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const dataOf = (block: string) =>
    block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .join("\n");
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end = buffer.indexOf("\n\n");
    while (end >= 0) {
      const data = dataOf(buffer.slice(0, end));
      buffer = buffer.slice(end + 2);
      if (data) yield JSON.parse(data) as AguiEvent;
      end = buffer.indexOf("\n\n");
    }
  }
  // An event the stream ended on without the blank line after it is still an event.
  const rest = dataOf(buffer);
  if (rest) yield JSON.parse(rest) as AguiEvent;
}

export interface Option {
  id: string;
  name: string;
  kind: string;
}

export interface PermissionRequest {
  id: string;
  tool: string;
  input: Record<string, unknown>;
  options: Option[];
}

export type Item =
  | { kind: "message"; id: string; role: "user" | "assistant" | "reasoning"; text: string }
  | { kind: "tool"; id: string; name: string; args: string; result: string | null };

export interface Conversation {
  items: Item[];
  running: boolean;
  error: string | null;
  ask: PermissionRequest | null;
  session: string | null;
  continuedAsNew: boolean;
}

export const EMPTY: Conversation = {
  items: [],
  running: false,
  error: null,
  ask: null,
  session: null,
  continuedAsNew: false,
};

interface SnapshotMessage {
  id: string;
  role: string;
  content?: string;
  toolCallId?: string;
  toolCalls?: { id: string; function: { name: string; arguments: string } }[];
}

function fromSnapshot(messages: SnapshotMessage[]): Item[] {
  const items: Item[] = [];
  for (const message of messages) {
    if (message.role === "user" || message.role === "assistant") {
      if (message.content) {
        items.push({ kind: "message", id: message.id, role: message.role, text: message.content });
      }
      for (const call of message.toolCalls ?? []) {
        items.push({
          kind: "tool",
          id: call.id,
          name: call.function.name,
          args: call.function.arguments,
          result: null,
        });
      }
    } else if (message.role === "tool") {
      const call = items.find((i) => i.kind === "tool" && i.id === message.toolCallId);
      if (call?.kind === "tool") call.result = message.content ?? "";
    }
  }
  return items;
}

function extend(items: Item[], id: string, change: (item: Item) => Item): Item[] {
  return items.map((item) => (item.id === id ? change(item) : item));
}

/** `conversation` after `event`. */
export function reduce(conversation: Conversation, event: AguiEvent): Conversation {
  const text = (key: string) => String(event[key] ?? "");
  switch (event.type) {
    case "MESSAGES_SNAPSHOT":
      return { ...conversation, items: fromSnapshot(event.messages as SnapshotMessage[]) };
    case "RUN_STARTED":
      return { ...conversation, running: true, error: null };
    case "RUN_FINISHED":
      return { ...conversation, running: false, ask: null };
    case "RUN_ERROR":
      return { ...conversation, running: false, ask: null, error: text("message") };
    case "TEXT_MESSAGE_START":
    case "REASONING_MESSAGE_START": {
      const role = event.type === "TEXT_MESSAGE_START" ? "assistant" : "reasoning";
      const item: Item = { kind: "message", id: text("messageId"), role, text: "" };
      return { ...conversation, items: [...conversation.items, item] };
    }
    case "TEXT_MESSAGE_CONTENT":
    case "REASONING_MESSAGE_CONTENT":
      return {
        ...conversation,
        items: extend(conversation.items, text("messageId"), (item) =>
          item.kind === "message" ? { ...item, text: item.text + text("delta") } : item,
        ),
      };
    case "TOOL_CALL_START": {
      const item: Item = {
        kind: "tool",
        id: text("toolCallId"),
        name: text("toolCallName"),
        args: "",
        result: null,
      };
      return { ...conversation, items: [...conversation.items, item] };
    }
    case "TOOL_CALL_ARGS":
      return {
        ...conversation,
        items: extend(conversation.items, text("toolCallId"), (item) =>
          item.kind === "tool" ? { ...item, args: item.args + text("delta") } : item,
        ),
      };
    case "TOOL_CALL_RESULT":
      return {
        ...conversation,
        items: extend(conversation.items, text("toolCallId"), (item) =>
          item.kind === "tool" ? { ...item, result: text("content") } : item,
        ),
      };
    case "CUSTOM":
      if (event.name === "permission_request") {
        return { ...conversation, ask: event.value as PermissionRequest };
      }
      if (event.name === "session") {
        return { ...conversation, session: (event.value as { id: string }).id };
      }
      if (event.name === "continued_as_new") return { ...conversation, continuedAsNew: true };
      return conversation;
    default:
      return conversation;
  }
}

/** A user turn, shown the moment it is sent. */
export function asked(conversation: Conversation, prompt: string): Conversation {
  const id = `sent-${conversation.items.length}`;
  const item: Item = { kind: "message", id, role: "user", text: prompt };
  return { ...conversation, items: [...conversation.items, item] };
}
