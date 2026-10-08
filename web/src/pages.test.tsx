// The overview, unit and usage pages, rendered from the API's recorded answers.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "./App";
import { recordedApi, UNITS } from "./test/api";

function open(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

// The state each recorded unit is in, and the cause and holder the record gives it.
const STATES: [string, string, string | null, string][] = [
  ["feature/1", "merged", "merged", ""],
  ["feature/2", "in_review", null, ""],
  ["feature/3", "blocked", null, ""],
  ["feature/4", "planned", null, ""],
  ["feature/5", "held", "review_escalated_class", "review"],
  ["feature/6", "failed", "failed", ""],
  ["feature/7", "running", null, ""],
  ["feature/8", "satisfied", null, ""],
  ["feature/9", "closed", "closed", ""],
];

beforeEach(() => {
  recordedApi();
});

describe("the shell", () => {
  it("lays out a list, a header, an outlet and a chat panel", async () => {
    open("/");

    expect(await screen.findByRole("navigation")).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: /chat/i })).toBeInTheDocument();
  });
});

describe("the overview", () => {
  it("lists every unit under its own name with its state", async () => {
    open("/");

    for (const [name, state] of STATES) {
      const row = (await screen.findByRole("link", { name: new RegExp(`^${name}\\b`) })).closest(
        "[data-unit]",
      ) as HTMLElement;
      expect(row).toHaveAttribute("data-unit", name);
      expect(within(row).getByText(state, { exact: false })).toBeInTheDocument();
    }
  });

  it("shows the cause of a unit that has one, from the record", async () => {
    open("/");

    const failed = (await screen.findByRole("link", { name: /^feature\/6\b/ })).closest(
      "[data-unit]",
    ) as HTMLElement;
    expect(within(failed).getByText(/failed/)).toBeInTheDocument();
    const held = screen.getByRole("link", { name: /^feature\/5\b/ }).closest(
      "[data-unit]",
    ) as HTMLElement;
    expect(within(held).getByText(/review_escalated_class|review escalated class/i)).toBeVisible();
  });
});

describe.each(STATES)("the page of %s", (name, state, cause, heldBy) => {
  it("shows its state and its cause from the record", async () => {
    open(`/units/${name}`);

    const header = await screen.findByRole("heading", { name });
    expect(header).toBeInTheDocument();
    const main = screen.getByRole("main");
    expect(within(main).getByText(state, { exact: false })).toBeInTheDocument();
    if (cause) {
      expect(within(main).getByText(cause.replaceAll("_", " "), { exact: false })).toBeVisible();
    }
    if (heldBy) {
      expect(within(main).getByText(new RegExp(`held by:?\\s*${heldBy}`, "i"))).toBeVisible();
    }
  });
});

describe("a unit's page", () => {
  it("shows who holds a held unit from the record, not from the note", async () => {
    // The note of a held unit may name anyone; the recorded holder is what is shown.
    const held = { ...UNITS["feature/5"], note: "held by a person", held_by: "toolchain" };
    const api = recordedApi();
    api.answer("/api/units/feature/5", held);

    open("/units/feature/5");

    expect(await screen.findByText(/held by:?\s*toolchain/i)).toBeVisible();
    expect(screen.queryByText(/held by:?\s*person/i)).not.toBeInTheDocument();
  });

  it("draws the history as a timeline of state, cause and note", async () => {
    open("/units/feature/1");

    const timeline = await screen.findByRole("list", { name: /history/i });
    const entries = within(timeline).getAllByRole("listitem");
    expect(entries).toHaveLength(UNITS["feature/1"].history.length);
    expect(entries[0]).toHaveTextContent(/planned/);
    expect(entries[2]).toHaveTextContent(/merged/);
    expect(entries[2]).toHaveTextContent("merged");
  });

  it("lists branch, base, pull request, dependencies and merge gates with their states", async () => {
    open("/units/feature/3");

    const main = screen.getByRole("main");
    expect(await within(main).findByText("main")).toBeVisible();
    const gates = await within(main).findByRole("list", { name: /merge gates/i });
    expect(within(gates).getByRole("link", { name: /feature\/2/ })).toBeVisible();
    expect(gates).toHaveTextContent(/in_review|in review/);
    const needs = within(main).getByRole("list", { name: /dependencies/i });
    expect(needs).toHaveTextContent("feature/2");

    open("/units/feature/2");
    expect(await screen.findByText(/#?12\b/)).toBeVisible();
    expect(screen.getByText("spec/feature/2")).toBeVisible();
  });

  it("shows the unit's usage from the same answer as the usage report", async () => {
    const api = recordedApi();
    open("/units/feature/2");

    await screen.findByRole("heading", { name: "feature/2" });
    await userEvent.click(screen.getByRole("tab", { name: /usage/i }));

    await screen.findByText(/cost/i);
    expect(api.requests).toContainEqual(expect.stringMatching(/^\/api\/usage\?.*unit=feature%2F2/));
  });
});

describe("the usage page", () => {
  it("shows the report's rows and total for the default grouping", async () => {
    open("/usage");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("add-marker/1")).toBeVisible();
    expect(within(table).getByText("add-marker/2")).toBeVisible();
    expect(within(table).getByText(/total/i)).toBeVisible();
    expect(within(table).getByText("1.25", { exact: false })).toBeVisible();
  });

  it("asks the report for another grouping when one is chosen", async () => {
    const api = recordedApi();
    open("/usage");
    await screen.findByRole("table");

    await userEvent.selectOptions(screen.getByRole("combobox", { name: /group by/i }), "node");

    expect(await screen.findByText("implement")).toBeVisible();
    expect(api.requests).toContain("/api/usage?by=node");
  });
});
