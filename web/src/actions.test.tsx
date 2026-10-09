// The unit page's action buttons: enabled from what the server says a unit allows, disabled
// with the CLI's reason otherwise, and posting to the action endpoint when pressed.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "./App";
import { recordedApi, UNITS } from "./test/api";

const NAMES = ["requeue", "hold", "release", "approve"];
const RUNNING = "feature/7 is running; only a failed or held unit can be requeued";

function actions(open: string[], reason: string) {
  return NAMES.map((name) => ({
    name,
    enabled: open.includes(name),
    reason: open.includes(name) ? "" : reason,
  }));
}

function open(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe("the action buttons", () => {
  it("are disabled for a running unit, with the reason the server gives", async () => {
    const api = recordedApi();
    api.answer("/api/units/feature/7", { ...UNITS["feature/7"], actions: actions([], RUNNING) });

    open("/units/feature/7");

    for (const name of NAMES) {
      const button = await screen.findByRole("button", { name: new RegExp(name, "i") });
      expect(button).toBeDisabled();
      expect(button).toHaveAccessibleDescription(RUNNING);
    }
    expect(screen.getAllByText(RUNNING)).toHaveLength(NAMES.length);
  });

  it("follow the unit's new state after an action succeeds", async () => {
    const api = recordedApi();
    let answered = 0;
    api.answer("/api/units/feature/6", () =>
      answered++ === 0
        ? { ...UNITS["feature/6"], actions: actions(["requeue"], "") }
        : {
            ...UNITS["feature/6"],
            state: "planned",
            actions: actions(
              [],
              "feature/6 is planned; only a failed or held unit can be requeued",
            ),
          },
    );
    api.answer(
      "/api/units/feature/6/actions/requeue",
      () => new Response(JSON.stringify({ message: "feature/6 requeued" }), { status: 200 }),
    );
    open("/units/feature/6");

    await userEvent.click(await screen.findByRole("button", { name: /requeue/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: /requeue/i })).toBeDisabled());
    expect(screen.getAllByText(/planned/).length).toBeGreaterThan(0);
  });

  it("post the chosen action for a failed unit and show the answer", async () => {
    const api = recordedApi();
    api.answer("/api/units/feature/6", {
      ...UNITS["feature/6"],
      actions: actions(["requeue"], ""),
    });
    api.answer(
      "/api/units/feature/6/actions/requeue",
      () => new Response(JSON.stringify({ message: "feature/6 requeued" }), { status: 200 }),
    );
    open("/units/feature/6");

    await userEvent.click(await screen.findByRole("button", { name: /requeue/i }));

    expect(api.sent).toContainEqual({
      method: "POST",
      path: "/api/units/feature/6/actions/requeue",
      body: expect.anything(),
    });
    expect(await screen.findByText(/feature\/6 requeued/)).toBeInTheDocument();
  });

  it("show a refusal as the reason the server gave", async () => {
    const api = recordedApi();
    api.answer("/api/units/feature/6", {
      ...UNITS["feature/6"],
      actions: actions(["requeue"], ""),
    });
    api.answer(
      "/api/units/feature/6/actions/requeue",
      () => new Response(JSON.stringify({ detail: "it was taken over" }), { status: 409 }),
    );
    open("/units/feature/6");

    await userEvent.click(await screen.findByRole("button", { name: /requeue/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("it was taken over");
  });
});
