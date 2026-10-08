import type { Metric, MetricSeries, MetricsAnswer } from "./api";
import { useApi } from "./useApi";

const WIDTH = 160;
const HEIGHT = 32;

function Chart({ series }: { series: MetricSeries[] }) {
  const points = series.flatMap((s) => s.points);
  if (points.length === 0) return <span>no data</span>;
  const times = points.map(([t]) => t);
  const values = points.map(([, v]) => v);
  const [t0, t1] = [Math.min(...times), Math.max(...times)];
  const top = Math.max(...values, 0);
  const x = (t: number) => (t1 === t0 ? WIDTH / 2 : ((t - t0) / (t1 - t0)) * WIDTH);
  const y = (v: number) => HEIGHT - (top === 0 ? 0 : (v / top) * HEIGHT);
  return (
    <svg width={WIDTH} height={HEIGHT} role="img" aria-label="chart">
      {series.map((s) => (
        <polyline
          key={JSON.stringify(s.labels)}
          fill="none"
          stroke="currentColor"
          points={s.points.map(([t, v]) => `${x(t)},${y(v)}`).join(" ")}
        />
      ))}
    </svg>
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

/** Every catalogued metric with its chart, and which source drew the charts. */
export function MetricsPage() {
  const answer = useApi<MetricsAnswer>("/api/metrics");
  if (answer === null) return null;
  if ("error" in answer) return <p role="alert">{answer.error}</p>;
  const { source, dashboard, metrics } = answer.data;
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
      <ul>
        {metrics.map((metric) => (
          <Entry key={metric.name} metric={metric} />
        ))}
      </ul>
    </>
  );
}
