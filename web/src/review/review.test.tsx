// The review tab at `/units/<change>/<n>/review`: the diff, its file tree, the reviewer's
// findings, and the highlight that the address, a click and a finding all share.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";

import { AppRoutes } from "../App";
import decision from "../test/recorded/review-decision.json";
import diff from "../test/recorded/review-diff.json";
import locateGone from "../test/recorded/review-locate-gone.json";
import locate from "../test/recorded/review-locate.json";
import state from "../test/recorded/review-state.json";
import { recordedApi, type Api } from "../test/api";

const MARKER = "src/marker.py";
const ROOT = "/units/feature/7";

function Where() {
  const { pathname, search } = useLocation();
  return <output aria-label="address">{pathname + search}</output>;
}

function open(address: string): Api {
  const api = recordedApi();
  api.answer(`/api${ROOT}/diff`, diff);
  api.answer(`/api${ROOT}/review`, state);
  render(
    <MemoryRouter initialEntries={[address]}>
      <AppRoutes />
      <Where />
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

function address(): URL {
  return new URL(screen.getByRole("status", { name: "address" }).textContent ?? "", "http://x");
}

function posts(): string[] {
  return vi
    .mocked(fetch)
    .mock.calls.filter(([, init]) => init?.method === "POST")
    .map(([url]) => String(url));
}

/** The writes the page has sent: method, path and the JSON body, in order. */
function sent(): [string, string, unknown][] {
  return vi
    .mocked(fetch)
    .mock.calls.filter(([, init]) => init?.method !== undefined)
    .map(([url, init]) => [init?.method ?? "", String(url), JSON.parse(String(init?.body))]);
}

function Go({ to }: { to: string }) {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(to)}>
      go {to}
    </button>
  );
}

const scrolled = vi.fn();
beforeEach(() => {
  scrolled.mockClear();
  Element.prototype.scrollIntoView = scrolled;
});

describe("the review tab", () => {
  it("shows the diff pinned to its commit, with a tree of the files", async () => {
    const api = open(`${ROOT}/review`);

    expect(await screen.findByRole("region", { name: MARKER })).toBeInTheDocument();
    const tree = screen.getByRole("navigation", { name: /files/i });
    for (const path of [MARKER, "src/gone.py", "src/new.py", "tests/test_marker.py"]) {
      expect(within(tree).getByText(path, { exact: false })).toBeInTheDocument();
    }
    expect(api.requests).toContain(`/api${ROOT}/diff`);
    expect(screen.getByText(diff.commit.slice(0, 7))).toBeInTheDocument();
  });

  it("shows the threads of the review beside their lines, outdated ones marked", async () => {
    open(`${ROOT}/review`);

    expect(await screen.findByRole("article", { name: /ui-0001/ })).toHaveTextContent(
      "Why was this renamed?",
    );
    expect(screen.getByRole("article", { name: /ui-0003/ })).toHaveTextContent(/outdated/i);
  });

  it("shows the reviewer's findings and follow-ups beside the diff", async () => {
    open(`${ROOT}/review`);

    const findings = await screen.findByRole("list", { name: /findings/i });
    expect(within(findings).getByText(/inserted line is not covered/)).toBeInTheDocument();
    expect(within(findings).getByText(/no docstring/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /follow-ups/i })).toHaveTextContent(
      "Add a changelog entry",
    );
  });
});

describe("selecting lines", () => {
  it("highlights a clicked line and a shift-clicked range, and creates no thread", async () => {
    open(`${ROOT}/review`);
    await screen.findByRole("region", { name: MARKER });
    const threads = screen.getAllByRole("article").length;

    const user = userEvent.setup();
    await user.click(line(MARKER, "new", 13));
    await user.keyboard("{Shift>}");
    await user.click(line(MARKER, "new", 15));
    await user.keyboard("{/Shift}");

    expect(selected()).toEqual([`${MARKER}:13`, `${MARKER}:14`, `${MARKER}:15`]);
    expect(screen.getAllByRole("article")).toHaveLength(threads);
    expect(posts()).toEqual([]);
  });

  it("removes the highlight on request", async () => {
    open(`${ROOT}/review`);
    await screen.findByRole("region", { name: MARKER });
    await userEvent.click(line(MARKER, "new", 13));

    await userEvent.click(screen.getByRole("button", { name: /clear (the )?highlight/i }));

    expect(selected()).toEqual([]);
    expect(address().search).not.toMatch(/lines=/);
  });

  it("writes the selection into the address as it changes", async () => {
    open(`${ROOT}/review`);
    await screen.findByRole("region", { name: MARKER });

    const user = userEvent.setup();
    await user.click(line(MARKER, "new", 13));
    expect(address().pathname).toBe(`${ROOT}/review`);
    expect(address().searchParams.get("file")).toBe(MARKER);
    expect(address().searchParams.get("lines")).toBe("13");

    await user.keyboard("{Shift>}");
    await user.click(line(MARKER, "new", 15));
    await user.keyboard("{/Shift}");
    expect(address().searchParams.get("lines")).toBe("13-15");
  });
});

describe("an address", () => {
  it("opens scrolled to its range with the range highlighted", async () => {
    open(`${ROOT}/review?file=${encodeURIComponent(MARKER)}&lines=12-14`);

    await screen.findByRole("region", { name: MARKER });

    await waitFor(() =>
      expect(selected()).toEqual([`${MARKER}:12`, `${MARKER}:13`, `${MARKER}:14`]),
    );
    await waitFor(() => expect(scrolled.mock.contexts).toContain(line(MARKER, "new", 12)));
  });

  it("names a single line without a range", async () => {
    open(`${ROOT}/review?file=${encodeURIComponent("src/new.py")}&lines=2`);

    await screen.findByRole("region", { name: "src/new.py" });

    await waitFor(() => expect(selected()).toEqual(["src/new.py:2"]));
  });

  it("is applied by a finding of the verdict, which scrolls to its line and highlights it", async () => {
    open(`${ROOT}/review`);
    const findings = await screen.findByRole("list", { name: /findings/i });

    await userEvent.click(
      within(findings).getByRole("button", { name: /inserted line is not covered/ }),
    );

    expect(selected()).toEqual([`${MARKER}:15`]);
    expect(scrolled.mock.contexts).toContain(line(MARKER, "new", 15));
    expect(address().searchParams.get("lines")).toBe("15");
  });

  it("opens an earlier commit's line at the nearest matching line", async () => {
    const api = recordedApi();
    api.answer(`/api${ROOT}/diff`, diff);
    api.answer(`/api${ROOT}/review`, state);
    api.answer(`/api${ROOT}/review/locate`, (url: URL) => {
      expect(url.searchParams.get("file")).toBe(MARKER);
      expect(url.searchParams.get("line")).toBe("14");
      expect(url.searchParams.get("side")).toBe("new");
      expect(url.searchParams.get("commit")).toBe("1d2e3f405162738495a6b7c8d9e0f1a2b3c4d5e6");
      return locate;
    });
    render(
      <MemoryRouter
        initialEntries={[
          `${ROOT}/review?file=${encodeURIComponent(MARKER)}&lines=14&commit=1d2e3f405162738495a6b7c8d9e0f1a2b3c4d5e6`,
        ]}
      >
        <AppRoutes />
      </MemoryRouter>,
    );

    await screen.findByRole("region", { name: MARKER });

    await waitFor(() => expect(selected()).toEqual([`${MARKER}:15`]));
    expect(scrolled.mock.contexts).toContain(line(MARKER, "new", 15));
    expect(screen.queryByRole("status", { name: /line note/i })).not.toBeInTheDocument();
  });

  it("says the line is gone when the earlier commit's line is not in the diff any more", async () => {
    const api = recordedApi();
    api.answer(`/api${ROOT}/diff`, diff);
    api.answer(`/api${ROOT}/review`, state);
    api.answer(`/api${ROOT}/review/locate`, locateGone);
    render(
      <MemoryRouter
        initialEntries={[
          `${ROOT}/review?file=${encodeURIComponent(MARKER)}&lines=14&commit=1d2e3f405162738495a6b7c8d9e0f1a2b3c4d5e6`,
        ]}
      >
        <AppRoutes />
      </MemoryRouter>,
    );

    const file = await screen.findByRole("region", { name: MARKER });

    expect(await screen.findByRole("status", { name: /line/i })).toHaveTextContent(/no longer/i);
    expect(selected()).toEqual([]);
    expect(scrolled.mock.contexts).toContain(file);
  });
});

describe("commenting", () => {
  const made = { ...state.threads[0], id: "ui-0009", body: "Why not a constant?", replies: [] };

  it("offers a comment only on a selection, and a selection alone sends nothing", async () => {
    open(`${ROOT}/review`);
    await screen.findByRole("region", { name: MARKER });
    expect(screen.queryByRole("button", { name: "Comment" })).not.toBeInTheDocument();

    await userEvent.click(line(MARKER, "new", 13));

    expect(screen.getByRole("button", { name: "Comment" })).toBeInTheDocument();
    expect(sent()).toEqual([]);
  });

  it("posts a range comment pinned to the diff's commit and shows the thread under its line", async () => {
    const api = open(`${ROOT}/review`);
    api.answer(`/api${ROOT}/review/threads`, { ...made, line: 15, start_line: 13 });
    await screen.findByRole("region", { name: MARKER });
    const user = userEvent.setup();
    await user.click(line(MARKER, "new", 13));
    await user.keyboard("{Shift>}");
    await user.click(line(MARKER, "new", 15));
    await user.keyboard("{/Shift}");

    await user.click(screen.getByRole("button", { name: "Comment" }));
    await user.type(screen.getByRole("textbox", { name: "Comment text" }), "Why not a constant?");
    await user.click(screen.getByRole("button", { name: "Post comment" }));

    expect(sent()).toEqual([
      [
        "POST",
        `/api${ROOT}/review/threads`,
        {
          path: MARKER,
          side: "new",
          line: 15,
          start_line: 13,
          commit: diff.commit,
          body: "Why not a constant?",
        },
      ],
    ]);
    const thread = await screen.findByRole("article", { name: /ui-0009/ });
    expect(line(MARKER, "new", 15).nextElementSibling).toBe(thread);
  });

  it("sends a null start_line for one line", async () => {
    const api = open(`${ROOT}/review`);
    api.answer(`/api${ROOT}/review/threads`, made);
    await screen.findByRole("region", { name: MARKER });
    const user = userEvent.setup();
    await user.click(line(MARKER, "old", 12));
    await user.click(screen.getByRole("button", { name: "Comment" }));
    await user.type(screen.getByRole("textbox", { name: "Comment text" }), "hm");
    await user.click(screen.getByRole("button", { name: "Post comment" }));

    expect(sent()[0][2]).toEqual({
      path: MARKER,
      side: "old",
      line: 12,
      start_line: null,
      commit: diff.commit,
      body: "hm",
    });
  });
});

describe("threads", () => {
  it("replies to a thread and shows the reply", async () => {
    const api = open(`${ROOT}/review`);
    const thread = state.threads[1];
    api.answer(`/api${ROOT}/review/threads/${thread.id}/replies`, {
      ...thread,
      replies: [{ body: "Agreed.", at: "2026-10-08T16:00:00+00:00" }],
    });
    const article = await screen.findByRole("article", { name: /ui-0002/ });

    await userEvent.type(within(article).getByRole("textbox", { name: /reply/i }), "Agreed.");
    await userEvent.click(within(article).getByRole("button", { name: "Reply" }));

    expect(sent()).toEqual([
      ["POST", `/api${ROOT}/review/threads/ui-0002/replies`, { body: "Agreed." }],
    ]);
    expect(await screen.findByText("Agreed.")).toBeInTheDocument();
  });

  it("resolves a thread, and opens a resolved one again", async () => {
    const api = open(`${ROOT}/review`);
    api.answer(`/api${ROOT}/review/threads/ui-0002`, { ...state.threads[1], resolved: true });
    api.answer(`/api${ROOT}/review/threads/ui-0004`, { ...state.threads[3], resolved: false });
    const first = await screen.findByRole("article", { name: /ui-0002/ });
    const second = screen.getByRole("article", { name: /ui-0004/ });

    await userEvent.click(within(first).getByRole("button", { name: "Resolve" }));
    await userEvent.click(within(second).getByRole("button", { name: "Unresolve" }));

    expect(sent()).toEqual([
      ["PATCH", `/api${ROOT}/review/threads/ui-0002`, { resolved: true }],
      ["PATCH", `/api${ROOT}/review/threads/ui-0004`, { resolved: false }],
    ]);
    expect(await within(first).findByRole("button", { name: "Unresolve" })).toBeInTheDocument();
  });
});

describe("the decision", () => {
  it("sends Approve with the summary and shows the recorded decision", async () => {
    const api = open(`${ROOT}/review`);
    api.answer(`/api${ROOT}/review/decision`, decision);
    await screen.findByRole("region", { name: MARKER });

    await userEvent.type(screen.getByRole("textbox", { name: /summary/i }), "Looks right.");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(sent()).toEqual([
      ["PUT", `/api${ROOT}/review/decision`, { decision: "approve", summary: "Looks right." }],
    ]);
    expect(await screen.findByRole("status", { name: /recorded decision/i })).toHaveTextContent(
      "Round 1: Approve — Looks right.",
    );
  });

  it("sends Request changes", async () => {
    const api = open(`${ROOT}/review`);
    api.answer(`/api${ROOT}/review/decision`, { ...decision, decision: "request_changes" });
    await screen.findByRole("region", { name: MARKER });

    await userEvent.click(screen.getByRole("button", { name: "Request changes" }));

    expect(sent()).toEqual([
      ["PUT", `/api${ROOT}/review/decision`, { decision: "request_changes", summary: "" }],
    ]);
  });

  it("shows the server's reason when the round already has a decision", async () => {
    const api = open(`${ROOT}/review`);
    api.answer(
      `/api${ROOT}/review/decision`,
      new Response(JSON.stringify({ detail: "round 1 already has a decision" }), { status: 409 }),
    );
    await screen.findByRole("region", { name: MARKER });

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("round 1 already has a decision");
  });
});

describe("the tab on the unit page", () => {
  it("says so when the review cannot be read", async () => {
    const api = recordedApi();
    api.answer(`/api${ROOT}/diff`, diff);
    api.answer(`/api${ROOT}/review`, new Response("{}", { status: 500 }));
    render(
      <MemoryRouter initialEntries={[`${ROOT}/review`]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("500");
  });

  it("is a tab beside the others, and the others lead back to the unit", async () => {
    open(`${ROOT}/review`);

    expect(await screen.findByRole("tab", { name: "Review", selected: true })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Logs" }));
    expect(address().pathname).toBe(ROOT);
  });

  it("opens a new address while it stays mounted", async () => {
    const api = recordedApi();
    api.answer(`/api${ROOT}/diff`, diff);
    api.answer(`/api${ROOT}/review`, state);
    render(
      <MemoryRouter initialEntries={[`${ROOT}/review`]}>
        <AppRoutes />
        <Where />
        <Go to={`${ROOT}/review?file=${encodeURIComponent(MARKER)}&lines=15`} />
      </MemoryRouter>,
    );
    await screen.findByRole("region", { name: MARKER });
    scrolled.mockClear();

    await userEvent.click(screen.getByRole("button", { name: /^go / }));

    await waitFor(() => expect(selected()).toEqual([`${MARKER}:15`]));
    expect(scrolled.mock.contexts).toContain(line(MARKER, "new", 15));
  });
});
