export interface UnitSummary {
  id: string;
  title: string;
  state: string;
  cause: string | null;
  held_by: string;
  note: string;
  branch: string;
  pr: number | null;
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

export interface MetricsAnswer {
  source: "prometheus" | "local";
  dashboard: string | null;
  metrics: Metric[];
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path}: ${response.status}`);
  }
  return (await response.json()) as T;
}
