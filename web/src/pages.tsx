import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { postAction } from "./api";
import type { Related, UnitDetail, UnitSummary } from "./api";
import { AgentTab } from "./agent";
import type { Attachment } from "./composer";
import { LogsTab } from "./logs";
import { ReviewTab } from "./review/tab";
import { unitPath } from "./unitName";
import { UsageTab, UsageTable } from "./usage";
import { useApi } from "./useApi";

/** The state, then the cause and who holds the unit, each from the record. */
function stateLine(unit: UnitSummary): ReactElement {
  const parts = [unit.status];
  if (unit.cause) parts.push(unit.cause.replaceAll("_", " "));
  const text = parts.join(" — ");
  return (
    <span data-state-line>
      {text}
      {unit.held_by && (
        <>
          {" — "}
          <span data-held-by={unit.held_by}>held by: {unit.held_by}</span>
        </>
      )}
    </span>
  );
}

export function Overview() {
  const pipeline = useApi<{ units: UnitSummary[] }>("/api/pipeline");
  return (
    <main>
      <h1>Pipeline</h1>
      {pipeline && "error" in pipeline && <p role="alert">{pipeline.error}</p>}
      {pipeline && "data" in pipeline && (
        <ul>
          {pipeline.data.units.map((unit) => (
            <li key={unit.id} data-unit={unit.id} title={unit.title}>
              <Link to={unitPath(unit.id)}>{unit.id}</Link> {stateLine(unit)}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function RelatedList({ label, items, link }: { label: string; items: Related[]; link: boolean }) {
  return (
    <ul aria-label={label}>
      {items.map((item) => (
        <li key={item.id}>
          {link ? <Link to={unitPath(item.id)}>{item.id}</Link> : item.id} {item.status}
        </li>
      ))}
    </ul>
  );
}

function Status({ unit }: { unit: UnitDetail }) {
  return (
    <>
      <p>{stateLine(unit)}</p>
      {unit.note && <p data-note>{unit.note}</p>}
      <dl>
        <dt>Review round</dt>
        <dd>{unit.review_round === null ? "—" : `Review round ${unit.review_round}`}</dd>
        <dt>Base</dt>
        <dd>{unit.base}</dd>
        <dt>Branch</dt>
        <dd>{unit.branch || "—"}</dd>
        <dt>Pull request</dt>
        <dd>{unit.pr === null ? "—" : `#${unit.pr}`}</dd>
      </dl>
      <h2>Dependencies</h2>
      <RelatedList label="Dependencies" items={unit.depends_on} link={false} />
      <h2>Merge gates</h2>
      <RelatedList label="Merge gates" items={unit.merge_gates} link />
    </>
  );
}

function Actions({ unit, changed }: { unit: UnitDetail; changed: () => void }) {
  const [answer, setAnswer] = useState<{ text: string; failed: boolean } | null>(null);
  const [pending, setPending] = useState(false);
  const run = (name: string) => {
    setPending(true);
    return postAction(unit.id, name)
      .then(
        (text) => {
          setAnswer({ text: text || `${unit.id}: ${name} done`, failed: false });
          changed();
        },
        (error: Error) => setAnswer({ text: error.message, failed: true }),
      )
      .finally(() => setPending(false));
  };
  return (
    <div>
      {(unit.actions ?? []).map((action) => (
        <span key={action.name}>
          <button
            disabled={pending || !action.enabled}
            title={action.enabled ? undefined : action.reason}
            aria-describedby={action.enabled ? undefined : `why-${action.name}`}
            onClick={() => void run(action.name)}
          >
            {action.name}
          </button>
          {!action.enabled && (
            <small id={`why-${action.name}`} data-reason>
              {action.reason}
            </small>
          )}
        </span>
      ))}
      {answer &&
        (answer.failed ? <p role="alert">{answer.text}</p> : <p role="status">{answer.text}</p>)}
    </div>
  );
}

const TABS = ["Status", "Logs", "Agent", "Usage", "Review"] as const;

/** The history as a timeline of state, cause and note, newest last. */
function History({ unit }: { unit: UnitDetail }) {
  return (
    <section>
      <h2>History</h2>
      <ol aria-label="History">
        {unit.history.map((entry, index) => (
          <li key={index}>
            <time dateTime={entry.at}>{entry.at.slice(0, 19).replace("T", " ")}</time>{" "}
            {[entry.state, entry.cause?.replaceAll("_", " "), entry.note]
              .filter(Boolean)
              .join(" — ")}
          </li>
        ))}
      </ol>
    </section>
  );
}

/** A unit; `review` opens it on the Review tab, which has an address of its own. */
export function UnitPage({ review = false }: { review?: boolean }) {
  const { change = "", number = "" } = useParams();
  const name = `${change}/${number}`;
  const [reload, setReload] = useState(0);
  const unit = useApi<UnitDetail>(`/api/units/${name}`, reload);
  const [chosen, setTab] = useState<(typeof TABS)[number]>("Status");
  const navigate = useNavigate();
  const location = useLocation();
  const arrived = (location.state as { attachment?: Attachment } | null)?.attachment;
  // What the review tab handed over, kept here until a turn carries it or its chip is removed.
  // The location state is consumed at once, so a reload does not bring it back.
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  useEffect(() => {
    if (!arrived) return;
    setAttachments([arrived]);
    setTab("Agent");
    navigate(location.pathname, { replace: true, state: null });
  }, [arrived, location.pathname, navigate]);
  const tab = review ? "Review" : chosen;

  function open(t: (typeof TABS)[number]) {
    if (t === "Review") navigate(`${unitPath(name)}/review`);
    else {
      setTab(t);
      if (review) navigate(unitPath(name));
    }
  }
  const detail = unit && "data" in unit ? unit.data : null;
  return (
    <>
      <div>
        <h1>{name}</h1>
        {detail && <p>{detail.title}</p>}
      </div>
      <main>
        {unit && "error" in unit && <p role="alert">{unit.error}</p>}
        {detail && (
          <>
            <div role="tablist">
              {TABS.map((t) => (
                <button key={t} role="tab" aria-selected={t === tab} onClick={() => open(t)}>
                  {t}
                </button>
              ))}
            </div>
            {tab === "Status" && <Status unit={detail} />}
            <Actions unit={detail} changed={() => setReload((n) => n + 1)} />
            {tab === "Logs" && <LogsTab name={name} />}
            {tab === "Agent" && (
              <AgentTab
                name={name}
                attachments={attachments}
                onSpent={(spent) =>
                  setAttachments((held) => held.filter((a) => !spent.includes(a)))
                }
              />
            )}
            {tab === "Usage" && <UsageTab name={name} />}
            {tab === "Review" && <ReviewTab />}
          </>
        )}
      </main>
      {detail && <History unit={detail} />}
    </>
  );
}

export function UsagePage() {
  return (
    <main>
      <h1>Usage</h1>
      <UsageTable />
    </main>
  );
}
