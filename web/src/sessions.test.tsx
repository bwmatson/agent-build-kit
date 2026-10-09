// The sessions page: what is listed, what is read-only and why, and the ways to go on.
// Rendered from the server's recorded answers.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "./App";
import {
  CHAT,
  HELD_SESSION,
  IDLE_SESSION,
  UNLOADABLE_SESSION,
  recordedApi,
  stream,
} from "./test/api";

async function openSessions() {
  render(
    <MemoryRouter initialEntries={["/sessions"]}>
      <AppRoutes />
    </MemoryRouter>,
  );
  return screen.findByRole("list", { name: "Sessions" });
}

describe("the sessions page", () => {
  it("lists the sessions with where they run and which a process holds", async () => {
    recordedApi();

    const list = await openSessions();

    const held = within(list).getByText("Fix the bug").closest("li") as HTMLElement;
    expect(held).toHaveTextContent("claude_code");
    expect(held).toHaveTextContent("/work/project");
    expect(held).toHaveTextContent(/held by a running process/i);
    const idle = within(list).getByText("Idle one").closest("li") as HTMLElement;
    expect(idle).not.toHaveTextContent(/held by/i);
    expect(within(list).getAllByText(/^unit feature\/2$/).length).toBeGreaterThan(0);
  });

  it("shows a session a process holds read-only, with its history, and offers a fork", async () => {
    recordedApi();
    await openSessions();

    await userEvent.click(screen.getByRole("button", { name: "Fix the bug" }));

    expect(await screen.findByRole("status")).toHaveTextContent(/read-only: process \d+ holds/i);
    expect(screen.getByRole("list", { name: "History" })).toHaveTextContent(
      "I found the cause in the parser.",
    );
    expect(screen.getByRole("radio", { name: "Fork and continue" })).toBeChecked();
    expect(screen.queryByRole("radio", { name: "Continue" })).not.toBeInTheDocument();
  });

  it("forks a held session with the turn typed", async () => {
    const api = recordedApi();
    api.answer(`/api/sessions/claude_code/${HELD_SESSION}/fork`, () => stream(CHAT));
    await openSessions();
    await userEvent.click(screen.getByRole("button", { name: "Fix the bug" }));

    await userEvent.type(await screen.findByRole("textbox"), "Take it further.");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("Because.")).toBeVisible();
    const [sent] = api.sent.filter((r) => r.path.endsWith("/fork"));
    expect(sent.method).toBe("POST");
    expect(sent.body).toMatchObject({ prompt: "Take it further." });
  });

  it("continues an idle session in place by default, and can fork it instead", async () => {
    const api = recordedApi();
    api.answer(`/api/sessions/claude_code/${IDLE_SESSION}/continue`, () => stream(CHAT));
    api.answer(`/api/sessions/claude_code/${IDLE_SESSION}/fork`, () => stream(CHAT));
    await openSessions();
    await userEvent.click(screen.getByRole("button", { name: "Idle one" }));
    expect(await screen.findByRole("radio", { name: "Continue" })).toBeChecked();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    await userEvent.type(screen.getByRole("textbox"), "And then?");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    await screen.findByText("Because.");
    await userEvent.click(screen.getByRole("radio", { name: "Fork and continue" }));
    await userEvent.type(screen.getByRole("textbox"), "Or this?");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await vi.waitFor(() => expect(api.sent.filter((r) => r.method === "POST")).toHaveLength(2));
    const paths = api.sent.filter((r) => r.method === "POST").map((r) => r.path);
    expect(paths).toEqual([
      `/api/sessions/claude_code/${IDLE_SESSION}/continue`,
      `/api/sessions/claude_code/${IDLE_SESSION}/fork`,
    ]);
  });

  it("says an agent session it cannot resume can only be continued as a new one", async () => {
    const api = recordedApi();
    api.answer("/api/sessions", {
      sessions: [
        {
          id: UNLOADABLE_SESSION,
          runtime: "acp",
          cwd: "/work/trees/app/spec_feature_2",
          title: "Earlier I read the module",
          updated: "2026-10-08T23:56:02+00:00",
          held: false,
          loadable: null,
          unit: "feature/2",
        },
      ],
    });
    api.answer(`/api/sessions/acp/${UNLOADABLE_SESSION}/continue`, () => stream(CHAT));
    await openSessions();

    await userEvent.click(screen.getByRole("button", { name: /earlier i read the module/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      /only be continued as a new session/i,
    );
    expect(screen.getByRole("list", { name: "History" })).toHaveTextContent(
      "Earlier I read the module and found nothing to change.",
    );
    expect(screen.getByRole("radio", { name: "Continue as a new session" })).toBeChecked();
    await userEvent.type(screen.getByRole("textbox"), "Carry on.");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    await screen.findByText("Because.");
    expect(api.sent.filter((r) => r.method === "POST").at(-1)?.path).toBe(
      `/api/sessions/acp/${UNLOADABLE_SESSION}/continue`,
    );
  });
});

describe("the sessions page as a tab", () => {
  async function continueUnitSession(api: ReturnType<typeof recordedApi>) {
    api.answer("/api/sessions", {
      sessions: [
        {
          id: UNLOADABLE_SESSION,
          runtime: "acp",
          cwd: "/work/trees/app/spec_feature_2",
          title: "Earlier I read the module",
          updated: "2026-10-08T23:56:02+00:00",
          held: false,
          loadable: null,
          unit: "feature/2",
        },
      ],
    });
    api.answer(`/api/sessions/acp/${UNLOADABLE_SESSION}/continue`, () => stream(CHAT));
    const view = render(
      <MemoryRouter initialEntries={["/sessions"]}>
        <AppRoutes />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: /earlier i read the module/i }),
    );
    await userEvent.type(await screen.findByRole("textbox"), "Carry on.");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    await screen.findByText("Because.");
    return view;
  }

  it("holds the tab it takes turns as open until the page goes", async () => {
    const api = recordedApi();

    const view = await continueUnitSession(api);

    const turn = api.sent.find((r) => r.path.endsWith("/continue"));
    const tab = (turn?.body as { tab: string }).tab;
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes("/tabs/events"));
    expect(String(call?.[0])).toBe(`/api/tabs/events?tab=${tab}`);
    const signal = (call?.[1] as RequestInit).signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    view.unmount();

    expect(signal.aborted).toBe(true);
  });

  it("offers to release a unit its turn took, from the same tab", async () => {
    const api = recordedApi();
    api.answer("/api/units/feature/2/agent", (url: URL) => ({
      session: { id: "s", runtime: "acp", model: "m" },
      state: "attached",
      composer: { enabled: true, reason: "" },
      attached_by: `tab:${url.searchParams.get("tab")}`,
    }));
    await continueUnitSession(api);

    await userEvent.click(await screen.findByRole("button", { name: /release the unit/i }));

    const turn = api.sent.find((r) => r.path.endsWith("/continue"));
    const released = api.sent.find((r) => r.method === "DELETE");
    expect(released?.path).toBe("/api/units/feature/2/lease");
    expect(api.requests).toContain(
      `/api/units/feature/2/lease?tab=${(turn?.body as { tab: string }).tab}`,
    );
  });
});

describe("a new session", () => {
  async function openForm() {
    const api = recordedApi();
    // The list is a GET, a new session a POST to the same address.
    api.answer("/api/sessions", (_url: URL, init?: RequestInit) =>
      init?.method === "POST" ? stream(CHAT) : { sessions: [] },
    );
    render(
      <MemoryRouter initialEntries={["/sessions"]}>
        <AppRoutes />
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "New session" }));
    await screen.findByRole("region", { name: "New session" });
    return api;
  }

  it("starts a session in a unit's worktree on the chosen runtime and model", async () => {
    const api = await openForm();
    const form = screen.getByRole("region", { name: "New session" });
    await userEvent.selectOptions(within(form).getByLabelText("Runtime"), "acp");
    await userEvent.type(within(form).getByLabelText("Model"), "deep-2");
    await vi.waitFor(() =>
      expect(within(form).getByLabelText("Unit")).toHaveDisplayValue(/feature\/1/),
    );
    await userEvent.selectOptions(within(form).getByLabelText("Unit"), "feature/2");
    await userEvent.type(within(form).getByRole("textbox", { name: "Message" }), "Look around.");
    await userEvent.click(within(form).getByRole("button", { name: /send/i }));

    const sent = api.sent.find((r) => r.method === "POST" && r.path === "/api/sessions");
    expect(sent?.body).toMatchObject({
      runtime: "acp",
      model: "deep-2",
      unit: "feature/2",
      prompt: "Look around.",
    });
    expect(sent?.body).not.toHaveProperty("repo");
    const tab = (sent?.body as { tab: string }).tab;
    expect(api.requests).toContain(`/api/tabs/events?tab=${tab}`);
    expect(await screen.findByText("Because.")).toBeVisible();
  });

  it("starts one for a repo, and shows the streamed reply", async () => {
    const api = await openForm();
    const form = screen.getByRole("region", { name: "New session" });
    await userEvent.selectOptions(within(form).getByLabelText("For"), "repo");
    await vi.waitFor(() => expect(within(form).getByLabelText("Repo")).toHaveDisplayValue(/\w/));
    await userEvent.type(within(form).getByRole("textbox", { name: "Message" }), "Hi.");
    await userEvent.click(within(form).getByRole("button", { name: /send/i }));

    const sent = api.sent.find((r) => r.method === "POST" && r.path === "/api/sessions");
    expect(sent?.body).toMatchObject({ prompt: "Hi." });
    expect(sent?.body).toHaveProperty("repo");
    expect(sent?.body).not.toHaveProperty("unit");
    expect(await screen.findByText("Because.")).toBeVisible();
  });
});
