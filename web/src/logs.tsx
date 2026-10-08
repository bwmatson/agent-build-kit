import { useEffect, useState } from "react";

import { getJson } from "./api";
import type { RunChunk, RunInfo } from "./api";
import { useApi } from "./useApi";

const POLL_MS = 3000;

interface Entry {
  text: string;
  continuation: string[];
}

const UNIT_PREFIX = /^[\w.-]+\/\d+:\s*/;
const SAYS = /^says:\s*/;

/** A line with the unit's name stripped; a reply's indented lines join the line above. */
function entries(lines: RunChunk["lines"]): Entry[] {
  const out: Entry[] = [];
  for (const { text } of lines) {
    const last = out.at(-1);
    if (last && /^\s/.test(text)) {
      last.continuation.push(text.trim());
    } else {
      out.push({ text: text.replace(UNIT_PREFIX, "").trimEnd(), continuation: [] });
    }
  }
  return out;
}

interface Followed {
  lines: RunChunk["lines"];
  live: boolean;
  outcome: string | null;
  missing: boolean;
}

/** A run's lines, polled from the byte offset last read for as long as the run is live. */
function useRun(unit: string, run: RunInfo): Followed {
  const [followed, setFollowed] = useState<Followed>({
    lines: [],
    live: run.live,
    outcome: null,
    missing: false,
  });
  useEffect(() => {
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = async (offset: number, live: boolean) => {
      const query = offset ? `?offset=${offset}` : "";
      let chunk: RunChunk;
      try {
        chunk = await getJson<RunChunk>(`/api/units/${unit}/logs/${run.name}${query}`);
      } catch {
        // A failed read (a restart, a file being rewritten) keeps what is shown and
        // asks again from the same offset while the run was last known live.
        if (current && live) timer = setTimeout(() => void read(offset, live), POLL_MS);
        return;
      }
      if (!current) return;
      setFollowed((before) => ({
        lines: [...before.lines, ...chunk.lines],
        live: chunk.live,
        outcome: chunk.outcome,
        missing: chunk.missing,
      }));
      if (chunk.live && !chunk.missing && chunk.outcome === null) {
        timer = setTimeout(() => void read(chunk.offset, true), POLL_MS);
      }
    };
    void read(0, run.live);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [unit, run.name, run.live]);
  return followed;
}

function Reply({ entry }: { entry: Entry }) {
  return (
    <div data-reply>
      <div>{entry.text.replace(SAYS, "")}</div>
      {entry.continuation.map((line, index) => (
        <div key={index}>{line}</div>
      ))}
    </div>
  );
}

function Run({ unit, run }: { unit: string; run: RunInfo }) {
  const followed = useRun(unit, run);
  const ended = followed.outcome !== null;
  // An ended run's header says how it ended and when, so its "started" line is left out.
  const shown = entries(followed.lines).filter((e) => !(ended && e.text.endsWith(": started")));
  return (
    <div role="group" aria-label={run.step}>
      <h3>
        {run.step} {followed.live ? "live" : ended ? `ended: ${followed.outcome}` : ""}
      </h3>
      {followed.missing && <p>This run's file was removed.</p>}
      {shown.map((entry, index) =>
        SAYS.test(entry.text) ? (
          <Reply key={index} entry={entry} />
        ) : (
          <div key={index}>{entry.text}</div>
        ),
      )}
    </div>
  );
}

/** A unit's runs, one group per run, each following its log. */
export function LogsTab({ name }: { name: string }) {
  const runs = useApi<{ runs: RunInfo[] }>(`/api/units/${name}/logs`);
  if (runs === null) return null;
  if ("error" in runs) return <p role="alert">{runs.error}</p>;
  return (
    <>
      {runs.data.runs.map((run) => (
        <Run key={run.name} unit={name} run={run} />
      ))}
    </>
  );
}
