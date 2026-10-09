// The uncommitted changes of a chat, shown apart from the branch's diff, and a selection of the
// diff sent to the unit's agent as context. Rendered from the server's recorded answers.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "../App";
import agentPaused from "../test/recorded/agent-feature-2.json";
import diff from "../test/recorded/review-diff.json";
import state from "../test/recorded/review-state.json";
import working from "../test/recorded/review-working.json";
import { CHAT, recordedApi, stream, type Api } from "../test/api";

const MARKER = "src/marker.py";
const NOTES = "src/notes.py";
const ROOT = "/units/feature/7";

function open(address = `${ROOT}/review`): Api {
  const api = recordedApi();
  api.answer(`/api${ROOT}/diff`, diff);
  api.answer(`/api${ROOT}/review`, state);
  api.answer(`/api${ROOT}/review/working`, working);
  api.answer(`/api${ROOT}/agent`, agentPaused);
  api.answer(`/api${ROOT}/chat`, () => stream(CHAT));
  render(
    <MemoryRouter initialEntries={[address]}>
      <AppRoutes />
    </MemoryRouter>,
  );
  return api;
}

function line(path: string, side: "old" | "new", n: number): HTMLElement {
  const found = document.querySelector<HTMLElement>(
    `[data-path="${path}"][data-${side}-line="${n}"]`,
  );
  if (found === null) throw new Error(`no ${side} line ${n} of ${path}`);
  return found;
}

function selected(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[data-selected="true"]')).map(
    (el) => `${el.dataset.path}:${el.dataset.newLine ?? `-${el.dataset.oldLine}`}`,
  );
}

async function selectRange(path: string, from: number, to: number) {
  const user = userEvent.setup();
  await user.click(line(path, "new", from));
  if (to !== from) {
    await user.keyboard("{Shift>}");
    await user.click(line(path, "new", to));
    await user.keyboard("{/Shift}");
  }
  return user;
}

interface Sent {
  file: string;
  lines: number[];
  hunk: string;
  text: string;
}

function sentChat(api: Api) {
  return api.sent.filter((r) => r.path === `/api${ROOT}/chat`);
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

describe("the uncommitted changes", () => {
  it("are their own section, marked uncommitted, apart from the branch's files", async () => {
    open();

    const section = await screen.findByRole("region", { name: /uncommitted changes/i });

    expect(section).toHaveTextContent(/not (yet )?committed|uncommitted/i);
    expect(within(section).getByRole("region", { name: NOTES })).toBeInTheDocument();
    expect(within(section).getByRole("region", { name: "src/extra.py" })).toBeInTheDocument();
    expect(within(section).queryByRole("region", { name: MARKER })).not.toBeInTheDocument();
    const branch = await screen.findByRole("region", { name: MARKER });
    expect(section).not.toContainElement(branch);
  });

  it("accept a highlight, which creates no thread", async () => {
    const api = open();
    await screen.findByRole("region", { name: NOTES });

    await selectRange(NOTES, 1, 2);

    expect(selected()).toEqual([`${NOTES}:1`, `${NOTES}:2`]);
    expect(api.sent.filter((r) => r.method !== "GET")).toEqual([]);
  });

  it("refuse a comment, with the reason, and send nothing", async () => {
    const api = open();
    await screen.findByRole("region", { name: NOTES });

    await selectRange(NOTES, 1, 1);

    expect(screen.getByRole("button", { name: "Comment" })).toBeDisabled();
    const note = screen.getByRole("status", { name: /comment note/i });
    expect(note).toHaveTextContent(/uncommitted/i);
    expect(api.sent.filter((r) => r.method !== "GET")).toEqual([]);
  });
});

describe("asking the agent about a selection", () => {
  it("is offered on a selection and not before", async () => {
    open();
    await screen.findByRole("region", { name: MARKER });
    expect(screen.queryByRole("button", { name: /ask the agent/i })).not.toBeInTheDocument();

    await selectRange(MARKER, 13, 15);

    expect(screen.getByRole("button", { name: /ask the agent/i })).toBeInTheDocument();
  });

  it("opens the unit's agent tab with one chip for the selection", async () => {
    open();
    await screen.findByRole("region", { name: MARKER });
    const user = await selectRange(MARKER, 13, 15);

    await user.click(screen.getByRole("button", { name: /ask the agent/i }));

    expect(await screen.findByRole("tab", { name: "Agent", selected: true })).toBeInTheDocument();
    expect(await screen.findAllByText(/src\/marker\.py:13-15/)).toHaveLength(1);
    expect(screen.getByRole("textbox", { name: "Message" })).toBeEnabled();
  });

  it("puts the file, lines, hunk and text in the turn it sends", async () => {
    const api = open();
    await screen.findByRole("region", { name: MARKER });
    const user = await selectRange(MARKER, 13, 15);
    await user.click(screen.getByRole("button", { name: /ask the agent/i }));
    await user.type(await screen.findByRole("textbox", { name: "Message" }), "Why this?");

    await user.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => expect(sentChat(api)).toHaveLength(1));
    const body = sentChat(api)[0].body as { prompt: string; attachments: Sent[] };
    expect(body.prompt).toBe("Why this?");
    expect(body.attachments).toHaveLength(1);
    const [attached] = body.attachments;
    expect(attached.file).toBe(MARKER);
    expect(attached.lines).toEqual([13, 15]);
    expect(attached.text).toBe("line 13\nline 14\ninserted after fourteen");
    expect(attached.hunk).toContain("@@ -9,9 +9,10 @@");
    expect(attached.hunk).toContain("+inserted after fourteen");
    expect(attached).not.toMatchObject({ uncommitted: true });
  });

  it("marks a selection of uncommitted lines as uncommitted", async () => {
    const api = open();
    await screen.findByRole("region", { name: NOTES });
    const user = await selectRange(NOTES, 1, 2);
    await user.click(screen.getByRole("button", { name: /ask the agent/i }));
    await user.type(await screen.findByRole("textbox", { name: "Message" }), "What is this?");

    await user.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => expect(sentChat(api)).toHaveLength(1));
    const { attachments } = sentChat(api)[0].body as { attachments: unknown[] };
    expect(attachments).toEqual([
      {
        file: NOTES,
        lines: [1, 2],
        hunk: expect.stringContaining("@@ -0,0 +1,3 @@"),
        text: "one\ntwo",
        uncommitted: true,
      },
    ]);
  });
});
