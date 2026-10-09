// The agent tab: what the server streamed, the composer it enables or disables, a turn, a
// permission request, and giving the unit back. Rendered from the server's recorded answers.
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "./App";
import paused from "./test/recorded/agent-feature-2.json";
import running from "./test/recorded/agent-feature-7.json";
import { CHAT, CHAT_WITH_PERMISSION, recordedApi, stream } from "./test/api";

async function openAgent(unit: string) {
  render(
    <MemoryRouter initialEntries={[`/units/${unit}`]}>
      <AppRoutes />
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole("tab", { name: /agent/i }));
}

describe("the agent tab", () => {
  it("shows the history the server replays, tool calls included", async () => {
    recordedApi();

    await openAgent("feature/2");

    const history = await screen.findByRole("list", { name: "Conversation" });
    await vi.waitFor(() => expect(history).toHaveTextContent("Why?"));
    expect(history).toHaveTextContent("I'll add the marker to the app module.");
    expect(history).toHaveTextContent("Edit");
    expect(history).toHaveTextContent("has been updated");
  });

  it("disables the composer with the reason while a step runs", async () => {
    const api = recordedApi();
    api.answer("/api/units/feature/7/agent/events", () => stream(""));

    await openAgent("feature/7");

    expect(await screen.findByText(/a step is running; its work is streamed here/i)).toBeVisible();
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("enables the composer when the step it is streaming ends, without a reload", async () => {
    const api = recordedApi();
    const encoder = new TextEncoder();
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    api.answer("/api/units/feature/7/agent/events", () => {
      const body = new ReadableStream<Uint8Array>({
        start(c) {
          controller = c;
        },
      });
      return new Response(body, { headers: { "content-type": "text/event-stream" } });
    });
    let asked = 0;
    api.answer("/api/units/feature/7/agent", () => (asked++ === 0 ? running : paused));
    await openAgent("feature/7");
    expect(await screen.findByText(/a step is running; its work is streamed here/i)).toBeVisible();
    expect(screen.getByRole("textbox")).toBeDisabled();

    const run = { threadId: "feature/7", runId: "r1" };
    await act(async () => {
      for (const event of [
        { type: "RUN_STARTED", ...run },
        { type: "RUN_FINISHED", ...run, result: { stopReason: "end_turn" } },
      ]) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      }
    });

    await vi.waitFor(() => expect(screen.getByRole("textbox")).toBeEnabled());
    expect(screen.getByRole("button", { name: /send/i })).toBeEnabled();
    expect(screen.queryByText(/a step is running/i)).not.toBeInTheDocument();
  });

  it("sends a turn and shows the reply as it streams", async () => {
    const api = recordedApi();
    api.answer("/api/units/feature/2/chat", () => stream(CHAT));
    await openAgent("feature/2");

    await screen.findAllByText("Because.");
    const before = screen.getAllByText("Because.").length;

    await userEvent.type(await screen.findByRole("textbox"), "Why this approach?");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await vi.waitFor(() => expect(screen.getAllByText("Because.")).toHaveLength(before + 1));
    expect(screen.getByText("Why this approach?", { exact: false })).toBeVisible();
    const [sent] = api.sent.filter((r) => r.path === "/api/units/feature/2/chat");
    expect(sent.method).toBe("POST");
    expect(sent.body).toMatchObject({ prompt: "Why this approach?", attachments: [] });
    expect((sent.body as { tab: string }).tab).toMatch(/\w+/);
  });

  it("shows a permission request, waits, and sends the chosen option", async () => {
    const api = recordedApi();
    const events = CHAT_WITH_PERMISSION.split("\n\n").filter(Boolean);
    const asking = events.findIndex((e) => e.includes("permission_request"));
    const encoder = new TextEncoder();
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const push = (lines: string[]) =>
      controller.enqueue(encoder.encode(lines.map((l) => `${l}\n\n`).join("")));
    api.answer("/api/units/feature/2/chat", () => {
      const body = new ReadableStream<Uint8Array>({
        start(c) {
          controller = c;
        },
      });
      return new Response(body, { headers: { "content-type": "text/event-stream" } });
    });
    const id = JSON.parse(events[asking].replace(/^data: /, "")).value.id as string;
    api.answer(`/api/permissions/${id}`, {});
    await openAgent("feature/2");

    await userEvent.type(await screen.findByRole("textbox"), "List it.");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    await act(async () => push(events.slice(0, asking + 1)));

    const request = await screen.findByRole("alert", { name: /permission request/i });
    expect(request).toHaveTextContent("ls src");
    await userEvent.click(screen.getByRole("button", { name: "Allow once" }));
    expect(api.sent.some((r) => r.path === `/api/permissions/${id}`)).toBe(true);
    expect(api.sent.find((r) => r.path === `/api/permissions/${id}`)?.body).toEqual({
      option: "proceed_once",
    });

    await act(async () => {
      push(events.slice(asking + 1));
      controller.close();
    });
    expect(screen.queryByRole("alert", { name: /permission request/i })).not.toBeInTheDocument();
  });

  describe("when the agent flags a request against a requirement", () => {
    const REQUIREMENT = "The registry is written through its journal";
    const REASON = "The request writes the registry file directly.";
    const events = [
      { type: "RUN_STARTED", threadId: "feature/2", runId: "r1" },
      { type: "TEXT_MESSAGE_START", messageId: "m1", role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "This contradicts the change." },
      { type: "TEXT_MESSAGE_END", messageId: "m1" },
      {
        type: "CUSTOM",
        name: "spec_conflict",
        value: { requirement: REQUIREMENT, reason: REASON },
      },
      {
        type: "RUN_FINISHED",
        threadId: "feature/2",
        runId: "r1",
        result: { stopReason: "end_turn" },
      },
    ];
    const FLAGGED = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");

    async function flagged() {
      const api = recordedApi();
      api.answer("/api/units/feature/2/chat", () => stream(FLAGGED));
      await openAgent("feature/2");
      await userEvent.type(await screen.findByRole("textbox"), "Write the file directly.");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));
      const callout = await screen.findByRole("alert", { name: /spec conflict/i });
      return { api, callout };
    }

    it("shows a callout with the requirement, the reason and the three choices", async () => {
      const { callout } = await flagged();

      expect(callout).toHaveTextContent(REQUIREMENT);
      expect(callout).toHaveTextContent(REASON);
      for (const name of ["Proceed anyway", "Change the spec instead", "Cancel"]) {
        expect(within(callout).getByRole("button", { name })).toBeVisible();
      }
    });

    it("sends a confirming turn on the same session when told to proceed", async () => {
      const { api } = await flagged();
      api.answer("/api/units/feature/2/chat", () => stream(CHAT));

      await userEvent.click(screen.getByRole("button", { name: "Proceed anyway" }));

      await vi.waitFor(() =>
        expect(api.sent.filter((r) => r.path === "/api/units/feature/2/chat")).toHaveLength(2),
      );
      const [, proceed] = api.sent.filter((r) => r.path === "/api/units/feature/2/chat");
      expect(proceed.body).toMatchObject({ prompt: "Proceed anyway.", attachments: [] });
      expect(api.sent.some((r) => r.path === "/api/sessions" && r.method === "POST")).toBe(false);
      expect(screen.queryByRole("alert", { name: /spec conflict/i })).not.toBeInTheDocument();
    });

    it("opens a planning session from the flag when told to change the spec", async () => {
      const { api } = await flagged();
      api.answer("/api/sessions", () => stream(CHAT));

      await userEvent.click(screen.getByRole("button", { name: "Change the spec instead" }));

      await vi.waitFor(() =>
        expect(api.sent.some((r) => r.path === "/api/sessions" && r.method === "POST")).toBe(true),
      );
      const opened = api.sent.find((r) => r.path === "/api/sessions" && r.method === "POST");
      expect(opened?.body).toMatchObject({
        runtime: "claude_code",
        repo: "planning",
        prompt: `${REQUIREMENT}: ${REASON}`,
      });
      expect(await screen.findByRole("region", { name: "Planning session" })).toHaveTextContent(
        "Because.",
      );
      expect(screen.queryByRole("alert", { name: /spec conflict/i })).not.toBeInTheDocument();
    });

    it("dismisses the callout on cancel and sends nothing", async () => {
      const { api } = await flagged();

      await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

      expect(screen.queryByRole("alert", { name: /spec conflict/i })).not.toBeInTheDocument();
      expect(api.sent.filter((r) => r.path === "/api/units/feature/2/chat")).toHaveLength(1);
    });
  });

  it("gives the unit back to the pipeline when asked", async () => {
    const api = recordedApi();
    api.answer("/api/units/feature/2/agent", (url: URL) => ({
      session: { id: "s", runtime: "claude_code", model: "opus" },
      state: "attached",
      composer: { enabled: true, reason: "" },
      attached_by: `tab:${url.searchParams.get("tab")}`,
    }));
    await openAgent("feature/2");

    await userEvent.click(await screen.findByRole("button", { name: /release the unit/i }));

    const released = api.sent.find((r) => r.method === "DELETE");
    expect(released?.path).toBe("/api/units/feature/2/lease");
    expect(api.requests.some((r) => r.startsWith("/api/units/feature/2/lease?tab="))).toBe(true);
  });

  it("closes its stream with the page, which is what returns the unit", async () => {
    recordedApi();
    const view = render(
      <MemoryRouter initialEntries={["/units/feature/2"]}>
        <AppRoutes />
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByRole("tab", { name: /agent/i }));
    await screen.findByRole("list", { name: "Conversation" });
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes("/agent/events"));
    const signal = (call?.[1] as RequestInit).signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    view.unmount();

    expect(signal.aborted).toBe(true);
  });
});
