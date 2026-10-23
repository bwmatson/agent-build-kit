// The strip at the head of the review tab: the tier a unit's verdict gave it, why, and the
// places the reviewer pointed a person at or away from.
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "../App";
import diff from "../test/recorded/review-diff.json";
import state from "../test/recorded/review-state.json";
import { recordedApi } from "../test/api";

const ROOT = "/units/feature/7";
const REASON = "a changed path is protected";
const FOCUS = [{ place: "src/marker.py:12", reason: "the rename changes a public name" }];
const SKIPPABLE = [{ place: "docs/notes.md", reason: "wording only" }];

function open(answer: object) {
  const api = recordedApi();
  api.answer(`/api${ROOT}/diff`, diff);
  api.answer(`/api${ROOT}/review`, answer);
  render(
    <MemoryRouter initialEntries={[`${ROOT}/review`]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

/** The strip, found by its accessible name. */
function strip(): Promise<HTMLElement> {
  return screen.findByRole("complementary", { name: "Review tier" });
}

describe("the review tab's tier strip", () => {
  it("shows the tier and the reason above the threads, with the focus and skippable lists", async () => {
    open({ ...state, tier: "full", reason: REASON, focus: FOCUS, skippable: SKIPPABLE });

    const head = await strip();
    expect(head).toHaveTextContent("full");
    expect(head).toHaveTextContent(REASON);
    for (const entry of [...FOCUS, ...SKIPPABLE]) {
      expect(head).toHaveTextContent(entry.place);
      expect(head).toHaveTextContent(entry.reason);
    }
    const thread = await screen.findByText("Why was this renamed?");
    expect(head.compareDocumentPosition(thread) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each([
    ["full", "light"],
    ["light", "full"],
  ])("names %s in words, so it does not rest on colour", async (tier, other) => {
    open({ ...state, tier, reason: REASON, focus: [], skippable: [] });

    const head = await strip();
    expect(head).toHaveTextContent(new RegExp(`\\b${tier}\\b`));
    expect(head).toHaveTextContent(REASON);
    expect(head).not.toHaveTextContent(new RegExp(`\\b${other}\\b`));
  });

  it("renders nothing extra for an answer without a verdict", async () => {
    open(state);

    await screen.findByText("Why was this renamed?");
    expect(screen.queryByText(REASON)).not.toBeInTheDocument();
    expect(screen.queryByText(/^(auto|light|full)$/i)).not.toBeInTheDocument();
  });
});
