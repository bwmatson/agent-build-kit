// The logs tab: lines grouped by node, a live run followed, a reply shown whole.
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "./App";
import { RUN_IMPLEMENT, recordedApi } from "./test/api";

async function openLogs() {
  render(
    <MemoryRouter initialEntries={["/units/feature/7"]}>
      <AppRoutes />
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole("tab", { name: /logs/i }));
}

afterEach(() => {
  vi.useRealTimers();
});

describe("the logs tab", () => {
  it("groups the lines by the node that wrote them", async () => {
    recordedApi();

    await openLogs();

    const tests = await screen.findByRole("group", { name: /tests/i });
    expect(within(tests).getByText(/I will write the failing test first/)).toBeVisible();
    expect(within(tests).getByText(/uv run pytest tests\/test_marker.py/)).toBeVisible();
    const implement = screen.getByRole("group", { name: /implement/i });
    expect(within(implement).getByText(/uv run pytest$/)).toBeVisible();
    expect(within(implement).queryByText(/failing test first/)).not.toBeInTheDocument();
  });

  it("shows a reply of several lines in full, as one reply", async () => {
    recordedApi();

    await openLogs();

    const reply = (await screen.findByText(/Plan:/)).closest("[data-reply]") as HTMLElement;
    expect(reply).not.toBeNull();
    expect(reply).toHaveTextContent("1. add the marker module");
    expect(reply).toHaveTextContent("2. wire it into the CLI");
    expect(reply).toHaveTextContent("Then run the checks.");
  });

  it("marks a run with no outcome as live and one with an outcome as ended", async () => {
    recordedApi();

    await openLogs();

    expect(await screen.findByRole("group", { name: /implement/i })).toHaveTextContent(/live/i);
    expect(screen.getByRole("group", { name: /tests/i })).not.toHaveTextContent(/live/i);
  });

  it("follows a live run from the offset it last read, without reloading", async () => {
    const api = recordedApi();
    const path = `/api/units/feature/7/logs/${RUN_IMPLEMENT}`;
    const firstOffset = 316;
    api.answer(path, (url: URL) =>
      url.searchParams.get("offset") === String(firstOffset)
        ? {
            lines: [{ at: "2026-09-24T05:50:20+00:00", text: "feature/7:   says: all green" }],
            offset: 380,
            live: false,
            outcome: "ok",
            missing: false,
          }
        : {
            lines: [{ at: "2026-09-24T05:50:01+00:00", text: "feature/7: implement: started" }],
            offset: firstOffset,
            live: true,
            outcome: null,
            missing: false,
          },
    );
    vi.useFakeTimers({ shouldAdvanceTime: true });

    await openLogs();
    expect(await screen.findByText(/implement: started|started/)).toBeVisible();
    expect(screen.queryByText(/all green/)).not.toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(await screen.findByText(/all green/)).toBeVisible();
    expect(api.requests).toContain(`${path}?offset=${firstOffset}`);
  });

  it("stops polling a run once it has an outcome", async () => {
    const api = recordedApi();
    vi.useFakeTimers({ shouldAdvanceTime: true });

    await openLogs();
    await screen.findByRole("group", { name: /tests/i });
    const ended = `/api/units/feature/7/logs/`;
    const before = api.requests.filter((r) => r.includes(ended) && r.includes("tests.log")).length;

    await act(() => vi.advanceTimersByTimeAsync(60_000));

    const after = api.requests.filter((r) => r.includes(ended) && r.includes("tests.log")).length;
    expect(after).toBe(before);
  });

  it("keeps what it showed when a run's file is removed between polls", async () => {
    const api = recordedApi();
    const path = `/api/units/feature/7/logs/${RUN_IMPLEMENT}`;
    let polled = false;
    api.answer(path, (url: URL) => {
      if (!polled) {
        polled = true;
        return {
          lines: [{ at: "2026-09-24T05:50:01+00:00", text: "feature/7: implement: started" }],
          offset: 316,
          live: true,
          outcome: null,
          missing: false,
        };
      }
      return { lines: [], offset: Number(url.searchParams.get("offset")), live: false, outcome: null, missing: true };
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });

    await openLogs();
    await screen.findByText(/started/);
    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(screen.getByText(/started/)).toBeVisible();
    expect(screen.getByText(/removed|no longer|missing/i)).toBeVisible();
  });
});
