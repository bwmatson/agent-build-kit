import { Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";

import type { Metric, MetricSeries, MetricsAnswer, Trace } from "./api";
import { useApi } from "./useApi";

const COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777"];
const WIDTH = 480;
const HEIGHT = 200;

function label(series: MetricSeries): string {
  const pairs = Object.entries(series.labels).map(([k, v]) => `${k}=${v}`);
  return pairs.length === 0 ? "all" : pairs.join(", ");
}

function when(t: number): string {
  return new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ");
}

function Chart({ series }: { series: MetricSeries[] }) {
  if (series.every((s) => s.points.length === 0)) return <span>no data</span>;
  const names = series.map(label);
  const rows = new Map<number, Record<string, number>>();
  series.forEach((s, i) => {
    for (const [t, v] of s.points) rows.set(t, { ...rows.get(t), t, [names[i]]: v });
  });
  const data = [...rows.values()].sort((a, b) => a.t - b.t);
  return (
    <div>
      <LineChart width={WIDTH} height={HEIGHT} data={data}>
        <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={when} />
        <YAxis width={60} />
        <Tooltip labelFormatter={(t) => when(Number(t))} />
        {names.map((name, i) => (
          <Line
            key={name}
            dataKey={name}
            stroke={COLORS[i % COLORS.length]}
            connectNulls
            isAnimationActive={false}
          />
        ))}
      </LineChart>
      <ul aria-label="legend">
        {names.map((name, i) => (
          <li key={name}>
            <span style={{ color: COLORS[i % COLORS.length] }}>■</span> {name}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Entry({ metric }: { metric: Metric }) {
  return (
    <li data-metric={metric.name}>
      <strong>{metric.name}</strong> <em>{metric.type}</em>{" "}
      {metric.attributes.map((attribute) => (
        <code key={attribute}>{attribute}</code>
      ))}
      <Chart series={metric.series} />
    </li>
  );
}

function Traces({ source, items }: { source: "tempo" | "local"; items: Trace[] }) {
  return (
    <section>
      <p data-testid="trace-source">
        {source === "tempo"
          ? "Recent traces from Tempo."
          : "Recent traces from local files (Tempo is unset or not answering)."}
      </p>
      <ul>
        {items.map((trace, i) => (
          <li key={`${trace.id}${trace.start}${i}`}>
            <strong>{trace.name}</strong> <time>{trace.start}</time> {trace.duration_ms} ms
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Every catalogued metric with its chart, and which source drew the charts. */
export function MetricsPage() {
  const answer = useApi<MetricsAnswer>("/api/metrics");
  if (answer === null) return null;
  if ("error" in answer) return <p role="alert">{answer.error}</p>;
  const { source, dashboard, metrics, traces } = answer.data;
  return (
    <>
      <p data-testid="metric-source">
        Charts from {source === "prometheus" ? "Prometheus" : "local files"}.
        {dashboard ? (
          <>
            {" "}
            <a href={dashboard}>Dashboard</a>
          </>
        ) : null}
      </p>
      <Traces source={traces.source} items={traces.items} />
      <ul>
        {metrics.map((metric) => (
          <Entry key={metric.name} metric={metric} />
        ))}
      </ul>
    </>
  );
}
