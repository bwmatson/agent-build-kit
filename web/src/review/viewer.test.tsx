// The viewer adapter: the patch as files and lines, with threads, a selection and collapse.
// Its contract is the DOM: a file is a region named by its path; a line is an element
// carrying `data-path` and `data-old-line` / `data-new-line` (the sides it has), and
// `data-selected` while highlighted; a thread is an article that directly follows the
// line it ends on. Nothing here names the diff library behind it.
/// <reference types="vite/client" />
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import diff from "../test/recorded/review-diff.json";
import state from "../test/recorded/review-state.json";
import type { LineRange, ReviewThread } from "./types";
import { DiffViewer } from "./viewer";

const THREADS = state.threads as ReviewThread[];
const MARKER = "src/marker.py";

function line(path: string, side: "old" | "new", n: number): HTMLElement {
  const found = document.querySelector<HTMLElement>(
    `[data-path="${path}"][data-${side}-line="${n}"]`,
  );
  if (found === null) throw new Error(`no ${side} line ${n} of ${path}`);
  return found;
}

function show(selection: LineRange | null = null, onSelect = vi.fn()) {
  render(
    <DiffViewer patch={diff.patch} threads={THREADS} selection={selection} onSelect={onSelect} />,
  );
  return onSelect;
}

describe("the viewer adapter", () => {
  it("renders every file of a recorded patch with its lines on both sides", () => {
    show();

    for (const path of [MARKER, "src/gone.py", "src/new.py", "tests/test_marker.py"]) {
      expect(screen.getByRole("region", { name: path })).toBeInTheDocument();
    }
    expect(line(MARKER, "new", 12)).toHaveTextContent("line twelve changed");
    expect(line(MARKER, "old", 12)).toHaveTextContent("line 12");
    expect(line(MARKER, "new", 15)).toHaveTextContent("inserted after fourteen");
    expect(line("src/gone.py", "old", 1)).toHaveTextContent("old");
    expect(line("src/new.py", "new", 2)).toHaveTextContent("return 1");
    // A context line is both an old and a new line; an added one has no old number.
    expect(line(MARKER, "new", 13)).toHaveAttribute("data-old-line", "13");
    expect(line(MARKER, "new", 15)).not.toHaveAttribute("data-old-line");
  });

  it("puts a thread under the line it ends on, on the side it was made on", () => {
    show();

    const added = screen.getByRole("article", { name: /ui-0001/ });
    expect(line(MARKER, "new", 12).nextElementSibling).toBe(added);
    expect(added).toHaveTextContent("Why was this renamed?");
    expect(added).toHaveTextContent("It matches the spec wording.");
    const removed = screen.getByRole("article", { name: /ui-0002/ });
    expect(line(MARKER, "old", 12).nextElementSibling).toBe(removed);
    expect(removed).toHaveTextContent("The old name was clearer.");
  });

  it("puts a thread on a range under the range's last line", () => {
    show();

    const ranged = screen.getByRole("article", { name: /ui-0003/ });
    expect(line("tests/test_marker.py", "new", 2).nextElementSibling).toBe(ranged);
    expect(ranged).toHaveTextContent("These two lines need a failing case.");
  });

  it("marks an outdated thread and a resolved one, and no other", () => {
    show();

    expect(screen.getByRole("article", { name: /ui-0003/ })).toHaveTextContent(/outdated/i);
    expect(screen.getByRole("article", { name: /ui-0004/ })).toHaveTextContent(/resolved/i);
    const plain = screen.getByRole("article", { name: /ui-0001/ });
    expect(plain).not.toHaveTextContent(/outdated/i);
    expect(plain).not.toHaveTextContent(/resolved/i);
  });

  it("reports a clicked line as a one-line range on the side it was clicked", async () => {
    const onSelect = show();

    await userEvent.click(line(MARKER, "new", 13));
    await userEvent.click(line(MARKER, "old", 12));

    expect(onSelect).toHaveBeenNthCalledWith(1, { path: MARKER, side: "new", start: 13, end: 13 });
    expect(onSelect).toHaveBeenNthCalledWith(2, { path: MARKER, side: "old", start: 12, end: 12 });
  });

  it("extends the selection to a shift-clicked line, in either direction", async () => {
    const onSelect = show({ path: MARKER, side: "new", start: 14, end: 14 });

    const user = userEvent.setup();
    await user.keyboard("{Shift>}");
    await user.click(line(MARKER, "new", 10));
    await user.keyboard("{/Shift}");

    expect(onSelect).toHaveBeenLastCalledWith({ path: MARKER, side: "new", start: 10, end: 14 });
  });

  it("highlights the selected range and no other line", () => {
    show({ path: MARKER, side: "new", start: 12, end: 14 });

    for (const n of [12, 13, 14]) {
      expect(line(MARKER, "new", n)).toHaveAttribute("data-selected", "true");
    }
    expect(line(MARKER, "new", 11)).not.toHaveAttribute("data-selected", "true");
    expect(line(MARKER, "new", 15)).not.toHaveAttribute("data-selected", "true");
    expect(line("src/new.py", "new", 1)).not.toHaveAttribute("data-selected", "true");
  });

  it("collapses a file to its header and expands it again, keeping the others", async () => {
    show();
    const file = screen.getByRole("region", { name: MARKER });

    await userEvent.click(within(file).getByRole("button", { name: /collapse/i }));

    expect(within(file).queryByText("line twelve changed")).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: /ui-0001/ })).not.toBeInTheDocument();
    expect(line("src/new.py", "new", 1)).toBeInTheDocument();
    await userEvent.click(within(file).getByRole("button", { name: /expand/i }));
    expect(within(file).getByText("line twelve changed")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: /ui-0001/ })).toBeInTheDocument();
  });

  it("draws a thread the server could not place at the top of its file, and one on a file out of the diff apart", async () => {
    show();

    const lost = screen.getByRole("article", { name: /ui-0005/ });
    const region = screen.getByRole("region", { name: MARKER });
    expect(region).toContainElement(lost);
    expect(lost).toHaveTextContent(/outdated/i);
    expect(lost).toHaveTextContent("This line was rewritten after I commented.");
    expect(lost.compareDocumentPosition(line(MARKER, "new", 9))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );

    const gone = screen.getByRole("article", { name: /ui-0006/ });
    expect(gone).toHaveTextContent(/outdated/i);
    expect(screen.getByRole("region", { name: /no longer in the diff/i })).toContainElement(gone);
    for (const file of screen.getAllByRole("region", { name: /\.py$/ })) {
      expect(file).not.toContainElement(gone);
    }

    await userEvent.click(within(region).getByRole("button", { name: /collapse/i }));
    expect(screen.getByRole("article", { name: /ui-0005/ })).toBeInTheDocument();
  });

  it("highlights a thread's lines while it is hovered, and nothing else", async () => {
    const onSelect = show();
    const lit = () =>
      Array.from(document.querySelectorAll<HTMLElement>('[data-selected="true"]')).map(
        (el) => `${el.dataset.path}:${el.dataset.newLine}`,
      );

    await userEvent.hover(screen.getByRole("article", { name: /ui-0003/ }));
    expect(lit()).toEqual(["tests/test_marker.py:1", "tests/test_marker.py:2"]);

    await userEvent.unhover(screen.getByRole("article", { name: /ui-0003/ }));
    expect(lit()).toEqual([]);

    await userEvent.hover(screen.getByRole("article", { name: /ui-0005/ }));
    expect(lit()).toEqual([]);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("is the only module that names the diff library", () => {
    const sources = import.meta.glob<string>("../**/*.{ts,tsx}", {
      query: "?raw",
      import: "default",
      eager: true,
    });
    const naming = Object.entries(sources)
      .filter(([, text]) => /from "(@pierre\/diffs|@git-diff-view\/react)[^"]*"/.test(text))
      .map(([path]) => path);

    expect(naming).toEqual(["./viewer.tsx"]);
  });
});

describe("a large patch", () => {
  const FILES = 200;
  type Watch = { callback: IntersectionObserverCallback; targets: Element[] };
  let watching: Watch[];

  beforeEach(() => {
    watching = [];
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        private watch: Watch;
        constructor(callback: IntersectionObserverCallback) {
          this.watch = { callback, targets: [] };
          watching.push(this.watch);
        }
        observe(target: Element) {
          this.watch.targets.push(target);
        }
        unobserve() {}
        disconnect() {}
        takeRecords() {
          return [];
        }
      },
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  const patch = Array.from({ length: FILES }, (_, i) =>
    [
      `diff --git a/pkg/f${i}.ts b/pkg/f${i}.ts`,
      "index 1111111..2222222 100644",
      `--- a/pkg/f${i}.ts`,
      `+++ b/pkg/f${i}.ts`,
      "@@ -1,3 +1,4 @@",
      " first",
      " second",
      `+added in ${i}`,
      " third",
      "",
    ].join("\n"),
  ).join("");

  /** Tell the page that something inside the file's region came into view. */
  function scrollTo(path: string) {
    const region = screen.getByRole("region", { name: path });
    act(() => {
      for (const { callback, targets } of watching) {
        for (const target of targets.filter((t) => region.contains(t))) {
          callback(
            [{ isIntersecting: true, target, intersectionRatio: 1 } as IntersectionObserverEntry],
            {} as IntersectionObserver,
          );
        }
      }
    });
  }

  it("lists all 200 files but draws the lines of the ones in view only", async () => {
    render(<DiffViewer patch={patch} threads={[]} selection={null} onSelect={vi.fn()} />);

    expect(screen.getAllByRole("region")).toHaveLength(FILES);
    await waitFor(() => expect(watching.length).toBeGreaterThan(0));
    expect(document.querySelectorAll("[data-path]").length).toBeLessThan(FILES * 4);
    expect(screen.queryByText("added in 150")).not.toBeInTheDocument();
  });

  it("shows a thread the server could not place before its file's lines are drawn", async () => {
    const lost = {
      ...THREADS[0],
      id: "ui-lost",
      path: "pkg/f10.ts",
      line: null,
      start_line: null,
      outdated: true,
    };
    render(<DiffViewer patch={patch} threads={[lost]} selection={null} onSelect={vi.fn()} />);
    await waitFor(() => expect(watching.length).toBeGreaterThan(0));

    expect(screen.getByRole("region", { name: "pkg/f10.ts" })).toContainElement(
      screen.getByRole("article", { name: /ui-lost/ }),
    );
    expect(screen.queryByText("added in 10")).not.toBeInTheDocument();
  });

  it("draws a file's lines when it scrolls into view, and not its neighbours'", async () => {
    render(<DiffViewer patch={patch} threads={[]} selection={null} onSelect={vi.fn()} />);
    await waitFor(() => expect(watching.length).toBeGreaterThan(0));

    scrollTo("pkg/f150.ts");

    expect(await screen.findByText("added in 150")).toBeInTheDocument();
    expect(screen.queryByText("added in 151")).not.toBeInTheDocument();
    expect(screen.queryByText("added in 100")).not.toBeInTheDocument();
  });
});
