import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactElement } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { getJson, sendJson } from "../api";
import { useApi } from "../useApi";
import type { Decision, LineRange, ReviewThread } from "./types";
import { DiffViewer, patchFiles } from "./viewer";

interface DiffAnswer {
  commit: string;
  base: string;
  base_commit: string;
  patch: string;
}

interface Finding {
  id: string;
  file: string;
  line: number | null;
  summary: string;
  required: boolean;
}

interface ReviewAnswer {
  round: number;
  threads: ReviewThread[];
  decisions: Decision[];
  findings: Finding[];
  follow_ups: string[];
}

/** Where the page scrolls to: a line, or only the file when the line is gone. */
interface Focus {
  path: string;
  side: "old" | "new";
  line: number | null;
}

function parseLines(value: string | null): { start: number; end: number } | null {
  const match = /^(\d+)(?:-(\d+))?$/.exec(value ?? "");
  if (!match) return null;
  const start = Number(match[1]);
  return { start, end: match[2] ? Number(match[2]) : start };
}

function quoted(path: string): string {
  return path.replace(/["\\]/g, "\\$&");
}

function lineSelector(focus: Focus): string {
  return `[data-path="${quoted(focus.path)}"][data-${focus.side}-line="${focus.line}"]`;
}

const DECISION_LABELS = { request_changes: "Request changes", approve: "Approve" } as const;

/** The composer for a comment on the selected lines. */
function Composer({
  selection,
  onPost,
}: {
  selection: LineRange;
  onPost: (body: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}>
        Comment
      </button>
    );
  }
  async function post() {
    setError(null);
    try {
      await onPost(body);
      setBody("");
      setOpen(false);
    } catch (failure) {
      setError((failure as Error).message);
    }
  }
  const where =
    selection.start === selection.end
      ? `${selection.start}`
      : `${selection.start}-${selection.end}`;
  return (
    <form
      aria-label="Comment"
      onSubmit={(event) => {
        event.preventDefault();
        void post();
      }}
    >
      <p>
        Comment on {selection.path}:{where}
      </p>
      <textarea aria-label="Comment text" value={body} onChange={(e) => setBody(e.target.value)} />
      <button type="submit" disabled={!body.trim()}>
        Post comment
      </button>
      <button type="button" onClick={() => setOpen(false)}>
        Cancel
      </button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}

/** The summary and the buttons that decide the round. */
function DecisionPanel({
  round,
  decided,
  onDecide,
}: {
  round: number;
  decided: Decision | null;
  onDecide: (decision: Decision["decision"], summary: string) => Promise<void>;
}) {
  const [summary, setSummary] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: Decision["decision"]) {
    setError(null);
    try {
      await onDecide(decision, summary);
    } catch (failure) {
      setError((failure as Error).message);
    }
  }
  return (
    <section aria-label="Decision">
      {decided && (
        <p role="status" aria-label="Recorded decision">
          Round {decided.round}: {DECISION_LABELS[decided.decision]}
          {decided.summary && ` — ${decided.summary}`}
        </p>
      )}
      <textarea
        aria-label={`Summary for round ${round}`}
        value={summary}
        onChange={(event) => setSummary(event.target.value)}
      />
      <button type="button" onClick={() => decide("request_changes")}>
        Request changes
      </button>
      <button type="button" onClick={() => decide("approve")}>
        Approve
      </button>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

/** The review tab: a unit's diff with its files, threads and findings, and a highlight
 * that lives in the address so a line or range can be linked to. Remounted for each
 * unit, so one unit's opening address is never applied to another. */
export function ReviewTab(): ReactElement {
  const { change = "", number = "" } = useParams();
  return <UnitReview key={`${change}/${number}`} name={`${change}/${number}`} />;
}

function UnitReview({ name }: { name: string }): ReactElement {
  const diff = useApi<DiffAnswer>(`/api/units/${name}/diff`);
  const review = useApi<ReviewAnswer>(`/api/units/${name}/review`);
  const [params, setParams] = useSearchParams();
  const [focus, setFocus] = useState<Focus | null>(null);
  const [located, setLocated] = useState<{ start: number; end: number } | null>(null);
  const [gone, setGone] = useState(false);
  // What this tab changed, which replaces what the review answered once there is any.
  const [edited, setEdited] = useState<ReviewThread[] | null>(null);
  const [decided, setDecided] = useState<Decision[] | null>(null);
  // The address this tab wrote itself: it is already applied, so it is not opened again.
  const written = useRef<string | null>(null);

  const patch = diff && "data" in diff ? diff.data.patch : null;
  const answer = review && "data" in review ? review.data : null;
  const file = params.get("file");
  const linesText = params.get("lines");
  const lines = useMemo(() => parseLines(linesText), [linesText]);
  const commit = params.get("commit");
  const side = params.get("side") === "old" ? "old" : "new";
  const address = [file, linesText, side, commit].join("|");
  const threads = edited ?? answer?.threads ?? [];
  const decisions = decided ?? answer?.decisions ?? [];

  useEffect(() => {
    if (patch === null || address === written.current) return;
    setLocated(null);
    setGone(false);
    if (!file || !lines) return;
    if (!commit) {
      setFocus({ path: file, side, line: lines.start });
      return;
    }
    const query = new URLSearchParams({ file, line: String(lines.start), side, commit });
    let current = true;
    const missing = () => {
      setGone(true);
      setFocus({ path: file, side, line: null });
    };
    getJson<{ line: number | null }>(`/api/units/${name}/review/locate?${query}`).then(
      ({ line }) => {
        if (!current) return;
        if (line === null) {
          missing();
          return;
        }
        setLocated({ start: line, end: line + lines.end - lines.start });
        setFocus({ path: file, side, line });
      },
      () => current && missing(),
    );
    return () => {
      current = false;
    };
  }, [patch, address, file, lines, commit, side, name]);

  useEffect(() => {
    if (focus === null || patch === null) return;
    const target =
      (focus.line !== null && document.querySelector(lineSelector(focus))) ||
      document.querySelector(`[data-file="${quoted(focus.path)}"]`);
    target?.scrollIntoView({ block: "center" });
  }, [focus, patch]);

  const selection: LineRange | null = useMemo(() => {
    if (!file || !lines) return null;
    if (commit) return located ? { path: file, side, ...located } : null;
    return { path: file, side, ...lines };
  }, [file, lines, commit, side, located]);

  function select(range: LineRange | null) {
    setLocated(null);
    setGone(false);
    if (range === null) {
      written.current = null;
      setParams({});
      return;
    }
    const text = range.start === range.end ? String(range.start) : `${range.start}-${range.end}`;
    const next: Record<string, string> = { file: range.path, lines: text };
    if (range.side === "old") next.side = "old";
    written.current = [range.path, text, range.side, null].join("|");
    setParams(next);
  }

  function show(finding: Finding) {
    if (finding.line === null) return;
    select({ path: finding.file, side: "new", start: finding.line, end: finding.line });
    setFocus({ path: finding.file, side: "new", line: finding.line });
  }

  const base = `/api/units/${name}/review`;
  const pinned = diff && "data" in diff ? diff.data.commit : "";

  async function comment(range: LineRange, body: string) {
    const made = await sendJson<ReviewThread>("POST", `${base}/threads`, {
      path: range.path,
      side: range.side,
      line: range.end,
      start_line: range.start === range.end ? null : range.start,
      commit: pinned,
      body,
    });
    setEdited((before) => [...(before ?? answer?.threads ?? []), made]);
  }

  function replaced(changed: ReviewThread) {
    setEdited((before) =>
      (before ?? answer?.threads ?? []).map((t) => (t.id === changed.id ? changed : t)),
    );
  }

  async function reply(thread: ReviewThread, body: string) {
    replaced(
      await sendJson<ReviewThread>("POST", `${base}/threads/${thread.id}/replies`, { body }),
    );
  }

  async function resolve(thread: ReviewThread, resolved: boolean) {
    replaced(await sendJson<ReviewThread>("PATCH", `${base}/threads/${thread.id}`, { resolved }));
  }

  async function decide(decision: Decision["decision"], summary: string) {
    const made = await sendJson<Decision>("PUT", `${base}/decision`, { decision, summary });
    setDecided((before) => [...(before ?? answer?.decisions ?? []), made]);
  }

  if (diff === null) return <p>Loading the diff…</p>;
  if ("error" in diff) return <p role="alert">{diff.error}</p>;
  const findings = answer?.findings ?? [];
  const followUps = answer?.follow_ups ?? [];
  const round = answer?.round ?? 1;

  return (
    <section aria-label="Review">
      <p>
        Pinned to <code>{diff.data.commit.slice(0, 7)}</code>
      </p>
      {review && "error" in review && <p role="alert">{review.error}</p>}
      <nav aria-label="Files">
        <ul>
          {patchFiles(diff.data.patch).map((path) => (
            <li key={path}>
              <button type="button" onClick={() => setFocus({ path, side: "new", line: null })}>
                {path}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      {gone && (
        <p role="status" aria-label="Line note">
          Line {lines?.start} of {file} in an earlier commit is no longer in the diff.
        </p>
      )}
      {selection && (
        <>
          <button type="button" onClick={() => select(null)}>
            Clear highlight
          </button>
          <Composer selection={selection} onPost={(body) => comment(selection, body)} />
        </>
      )}
      <ul aria-label="Findings">
        {findings.map((finding) => (
          <li key={finding.id}>
            {finding.line === null ? (
              finding.summary
            ) : (
              <button type="button" onClick={() => show(finding)}>
                {finding.summary}
              </button>
            )}
          </li>
        ))}
      </ul>
      <ul aria-label="Follow-ups">
        {followUps.map((point, index) => (
          <li key={index}>{point}</li>
        ))}
      </ul>
      <DecisionPanel
        round={round}
        decided={decisions.find((d) => d.round === round) ?? null}
        onDecide={decide}
      />
      <DiffViewer
        patch={diff.data.patch}
        threads={threads}
        selection={selection}
        onSelect={select}
        onReply={reply}
        onResolve={resolve}
        reveal={focus?.path ?? null}
      />
    </section>
  );
}
