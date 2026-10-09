export interface UnitSummary {
  id: string;
  title: string;
  state: string;
  cause: string | null;
  held_by: string;
  note: string;
  branch: string;
  pr: number | null;
  repo: string;
}

export interface Related {
  id: string;
  state: string;
}

export interface HistoryEntry {
  state: string;
  at: string;
  cause: string | null;
  note: string;
}

export interface UnitDetail extends UnitSummary {
  history: HistoryEntry[];
  base: string;
  depends_on: Related[];
  merge_gates: Related[];
  review_round: number | null;
  actions?: UnitAction[];
}

export interface UnitAction {
  name: string;
  enabled: boolean;
  reason: string;
}

export interface UsageRow {
  key: string;
  measured: {
    calls: number;
    input_tokens: number | null;
    output_tokens: number | null;
    cost_usd: number | null;
  };
}

export interface UsageReport {
  group_by: string;
  rows: UsageRow[];
  total: UsageRow;
}

export interface RunInfo {
  name: string;
  step: string;
  started: string;
  live: boolean;
}

export interface RunChunk {
  lines: { at: string; text: string }[];
  offset: number;
  live: boolean;
  outcome: string | null;
  missing: boolean;
}

export interface MetricSeries {
  labels: Record<string, string>;
  points: [number, number][];
}

export interface Metric {
  name: string;
  type: string;
  attributes: string[];
  series: MetricSeries[];
}

export interface Trace {
  id: string;
  name: string;
  start: string;
  duration_ms: number;
}

export interface MetricsAnswer {
  source: "prometheus" | "local";
  dashboard: string | null;
  traces: { source: "tempo" | "local"; items: Trace[] };
  metrics: Metric[];
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path}: ${response.status}`);
  }
  return (await response.json()) as T;
}

/** Post a unit action; the answer's message, or the reason it was refused. */
export async function postAction(unit: string, name: string): Promise<string> {
  const response = await fetch(`/api/units/${unit}/actions/${name}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({}),
  });
  const body = (await response.json().catch(() => ({}))) as { message?: string; detail?: string };
  if (!response.ok) {
    throw new Error(body.detail ?? `${name}: ${response.status}`);
  }
  return body.message ?? "";
}

/** Send `body` as JSON with `method`. A refusal throws the server's own `detail`. */
export async function sendJson<T>(method: string, path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = "";
    try {
      const answer = (await response.json()) as { detail?: unknown };
      detail = typeof answer.detail === "string" ? answer.detail : "";
    } catch {
      // The refusal had no JSON body; the status says enough.
    }
    throw new Error(detail || `${path}: ${response.status}`);
  }
  return (await response.json()) as T;
}
