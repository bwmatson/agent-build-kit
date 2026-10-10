import { parsePatchFiles } from "@pierre/diffs";
import type { FileDiffMetadata } from "@pierre/diffs";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent, ReactElement } from "react";

import type { LineRange, ReviewThread } from "./types";

export interface DiffViewerProps {
  patch: string;
  threads: ReviewThread[];
  selection: LineRange | null;
  onSelect: (range: LineRange | null) => void;
  /** Reply to a thread, or mark it resolved or open; omitted, a thread offers neither. */
  onReply?: (thread: ReviewThread, body: string) => Promise<void>;
  onResolve?: (thread: ReviewThread, resolved: boolean) => Promise<void>;
  /** A file to draw at once, so a line in it can be scrolled to before it is in view. */
  reveal?: string | null;
}

interface Row {
  old: number | null;
  new: number | null;
  text: string;
  kind: "context" | "add" | "delete";
}

function files(patch: string): FileDiffMetadata[] {
  return parsePatchFiles(patch).flatMap((parsed) => parsed.files);
}

/** The paths a patch changes, in patch order. */
export function patchFiles(patch: string): string[] {
  return files(patch).map((file) => file.name);
}

function text(line: string | undefined): string {
  return (line ?? "").replace(/\r?\n$/, "");
}

type Hunk = FileDiffMetadata["hunks"][number];

function hunkRows(file: FileDiffMetadata, hunk: Hunk): Row[] {
  const out: Row[] = [];
  let oldLine = hunk.deletionStart;
  let newLine = hunk.additionStart;
  for (const block of hunk.hunkContent) {
    if (block.type === "context") {
      for (let i = 0; i < block.lines; i++) {
        const content = text(file.additionLines[block.additionLineIndex + i]);
        out.push({ old: oldLine++, new: newLine++, text: content, kind: "context" });
      }
      continue;
    }
    for (let i = 0; i < block.deletions; i++) {
      const content = text(file.deletionLines[block.deletionLineIndex + i]);
      out.push({ old: oldLine++, new: null, text: content, kind: "delete" });
    }
    for (let i = 0; i < block.additions; i++) {
      const content = text(file.additionLines[block.additionLineIndex + i]);
      out.push({ old: null, new: newLine++, text: content, kind: "add" });
    }
  }
  return out;
}

function rows(file: FileDiffMetadata): Row[] {
  return file.hunks.flatMap((hunk) => hunkRows(file, hunk));
}

const MARKS = { context: " ", add: "+", delete: "-" } as const;

/** The hunks of `range.path` that hold lines of `range`, and the text of those lines, both from
 * the same parse the viewer draws. Null where the patch shows none of them. */
export function rangeContext(
  patch: string,
  range: LineRange,
): { hunk: string; text: string } | null {
  const file = files(patch).find((f) => f.name === range.path);
  if (!file) return null;
  const hunks: string[] = [];
  const picked: string[] = [];
  for (const hunk of file.hunks) {
    const lines = hunkRows(file, hunk);
    const inside = lines.filter((row) => {
      const n = range.side === "new" ? row.new : row.old;
      return n !== null && n >= range.start && n <= range.end;
    });
    if (inside.length === 0) continue;
    picked.push(...inside.map((row) => row.text));
    // The raw first line: it already holds any function context, and its line ending.
    const head = (hunk.hunkSpecs ?? "").replace(/\r?\n$/, "");
    hunks.push([head, ...lines.map((row) => MARKS[row.kind] + row.text)].join("\n"));
  }
  return picked.length === 0 ? null : { hunk: hunks.join("\n"), text: picked.join("\n") };
}

function inRange(selection: LineRange | null, path: string, side: "old" | "new", n: number | null) {
  return (
    selection !== null &&
    n !== null &&
    selection.path === path &&
    selection.side === side &&
    n >= selection.start &&
    n <= selection.end
  );
}

/** The lines a thread is about, for highlighting; null when it has no line to point at. */
function threadRange(thread: ReviewThread): LineRange | null {
  if (thread.line === null) return null;
  return {
    path: thread.path,
    side: thread.side,
    start: thread.start_line ?? thread.line,
    end: thread.line,
  };
}

function Thread({
  thread,
  onReply,
  onResolve,
  onHover,
}: {
  thread: ReviewThread;
  onHover: (thread: ReviewThread | null) => void;
  onReply?: DiffViewerProps["onReply"];
  onResolve?: DiffViewerProps["onResolve"];
}) {
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function attempt(action: () => Promise<void>, done?: () => void) {
    setError(null);
    try {
      await action();
      done?.();
    } catch (failure) {
      setError((failure as Error).message);
    }
  }

  return (
    <article
      aria-label={`Thread ${thread.id}`}
      data-thread={thread.id}
      onPointerEnter={() => onHover(thread)}
      onPointerLeave={() => onHover(null)}
    >
      {thread.outdated && <strong>Outdated</strong>}
      {thread.resolved && <strong>Resolved</strong>}
      <p>{thread.body}</p>
      {thread.replies.map((reply, index) => (
        <p key={index}>{reply.body}</p>
      ))}
      {onReply && (
        <>
          <textarea
            aria-label={`Reply to ${thread.id}`}
            value={reply}
            onChange={(event) => setReply(event.target.value)}
          />
          <button
            type="button"
            disabled={!reply.trim()}
            onClick={() =>
              attempt(
                () => onReply(thread, reply),
                () => setReply(""),
              )
            }
          >
            Reply
          </button>
        </>
      )}
      {onResolve && (
        <button type="button" onClick={() => attempt(() => onResolve(thread, !thread.resolved))}>
          {thread.resolved ? "Unresolve" : "Resolve"}
        </button>
      )}
      {error && <p role="alert">{error}</p>}
    </article>
  );
}

const FileSection = memo(function FileSection({
  file,
  threads,
  selection,
  onSelect,
  onReply,
  onResolve,
  onHover,
  hovered,
  drawn,
  watch,
}: {
  onHover: (thread: ReviewThread | null) => void;
  hovered: LineRange | null;
  file: FileDiffMetadata;
  threads: ReviewThread[];
  selection: LineRange | null;
  onSelect: (range: LineRange | null) => void;
  onReply?: DiffViewerProps["onReply"];
  onResolve?: DiffViewerProps["onResolve"];
  drawn: boolean;
  watch: (element: HTMLElement | null) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const path = file.name;
  const all = useMemo(() => rows(file), [file]);
  const lines = drawn ? all : [];
  // A thread with no line the diff shows (the server could not move it, or the diff does
  // not hold its line) is drawn at the top of the file, so it is never lost.
  const { unplaced, byLine } = useMemo(() => {
    const shown = new Set(all.flatMap((r) => [`new:${r.new}`, `old:${r.old}`]));
    const placed = new Map<string, ReviewThread[]>();
    const lost: ReviewThread[] = [];
    for (const t of threads) {
      const key = `${t.side}:${t.line}`;
      if (t.line === null || !shown.has(key)) lost.push(t);
      else placed.set(key, [...(placed.get(key) ?? []), t]);
    }
    return { unplaced: lost, byLine: placed };
  }, [all, threads]);

  function click(row: Row, event: MouseEvent) {
    const side = row.new !== null ? "new" : "old";
    const n = (side === "new" ? row.new : row.old) as number;
    const anchor =
      event.shiftKey && selection?.path === path && selection.side === side ? selection : null;
    const start = anchor ? Math.min(anchor.start, n) : n;
    const end = anchor ? Math.max(anchor.end, n) : n;
    onSelect({ path, side, start, end });
  }

  return (
    <section aria-label={path} data-file={path} ref={watch}>
      <h3>
        <button type="button" aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}>
          {collapsed ? "Expand" : "Collapse"} {path}
        </button>
      </h3>
      {unplaced.map((thread) => (
        <Thread
          key={thread.id}
          thread={thread}
          onReply={onReply}
          onResolve={onResolve}
          onHover={onHover}
        />
      ))}
      {!collapsed &&
        lines.map((row, index) => {
          const here = [
            ...(byLine.get(`new:${row.new}`) ?? []),
            ...(byLine.get(`old:${row.old}`) ?? []),
          ];
          const selected = [selection, hovered].some(
            (range) => inRange(range, path, "new", row.new) || inRange(range, path, "old", row.old),
          );
          return (
            <div key={index} style={{ display: "contents" }}>
              <div
                data-path={path}
                data-old-line={row.old ?? undefined}
                data-new-line={row.new ?? undefined}
                data-kind={row.kind}
                data-selected={selected ? "true" : undefined}
                onClick={(event) => click(row, event)}
              >
                <span>{row.old}</span> <span>{row.new}</span> <code>{row.text}</code>
              </div>
              {here.map((thread) => (
                <Thread
                  key={thread.id}
                  thread={thread}
                  onReply={onReply}
                  onResolve={onResolve}
                  onHover={onHover}
                />
              ))}
            </div>
          );
        })}
    </section>
  );
});

const NO_THREADS: ReviewThread[] = [];

/** The only module that knows which diff library draws the patch. A file's lines are
 * drawn when it first scrolls into view, so a large patch stays responsive. */
export function DiffViewer({
  patch,
  threads,
  selection,
  onSelect,
  onReply,
  onResolve,
  reveal = null,
}: DiffViewerProps): ReactElement {
  const parsed = useMemo(() => files(patch), [patch]);
  const observable = typeof IntersectionObserver !== "undefined";
  const [seen, setSeen] = useState<ReadonlySet<string>>(new Set());
  const observer = useRef<IntersectionObserver | null>(null);
  const root = useRef<HTMLDivElement | null>(null);
  const [hovered, setHovered] = useState<LineRange | null>(null);
  // The parent's handlers change with every render; the sections get ones that do not, so a
  // hover or a selection re-renders only the sections it concerns.
  const latest = useRef({ onSelect, onReply, onResolve });
  latest.current = { onSelect, onReply, onResolve };
  const select = useCallback((range: LineRange | null) => latest.current.onSelect(range), []);
  const reply = useMemo(
    () =>
      onReply && ((thread: ReviewThread, body: string) => latest.current.onReply!(thread, body)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [onReply === undefined],
  );
  const resolve = useMemo(
    () =>
      onResolve &&
      ((thread: ReviewThread, resolved: boolean) => latest.current.onResolve!(thread, resolved)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [onResolve === undefined],
  );
  const hover = useCallback(
    (thread: ReviewThread | null) => setHovered(thread && threadRange(thread)),
    [],
  );
  const { byPath, orphans } = useMemo(() => {
    const names = new Set(parsed.map((file) => file.name));
    const grouped = new Map<string, ReviewThread[]>();
    for (const t of threads) grouped.set(t.path, [...(grouped.get(t.path) ?? []), t]);
    return { byPath: grouped, orphans: threads.filter((t) => !names.has(t.path)) };
  }, [parsed, threads]);

  useEffect(() => {
    if (!observable) return;
    const watcher = new IntersectionObserver((entries) => {
      const names = entries
        .filter((entry) => entry.isIntersecting)
        .map((entry) => (entry.target as HTMLElement).dataset.file)
        .filter((name): name is string => name !== undefined);
      if (names.length) setSeen((before) => new Set([...before, ...names]));
    });
    observer.current = watcher;
    root.current?.querySelectorAll("[data-file]").forEach((el) => watcher.observe(el));
    return () => {
      watcher.disconnect();
      observer.current = null;
    };
  }, [observable, parsed]);

  const watch = useCallback((element: HTMLElement | null) => {
    if (element) observer.current?.observe(element);
  }, []);

  return (
    <div ref={root}>
      {parsed.map((file) => (
        <FileSection
          key={file.name}
          file={file}
          threads={byPath.get(file.name) ?? NO_THREADS}
          selection={selection?.path === file.name ? selection : null}
          onSelect={select}
          onReply={reply}
          onResolve={resolve}
          onHover={hover}
          hovered={hovered?.path === file.name ? hovered : null}
          drawn={!observable || seen.has(file.name) || reveal === file.name}
          watch={watch}
        />
      ))}
      {orphans.length > 0 && (
        <section aria-label="Threads on files no longer in the diff">
          <h3>Threads on files no longer in the diff</h3>
          {orphans.map((thread) => (
            <Thread
              key={thread.id}
              thread={thread}
              onReply={reply}
              onResolve={resolve}
              onHover={hover}
            />
          ))}
        </section>
      )}
    </div>
  );
}
