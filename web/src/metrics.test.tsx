// The metrics page: every catalogued metric, and which source drew the charts.
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "./App";
import { recordedApi } from "./test/api";

function metrics(source: string) {
  return {
    source,
    dashboard: null,
    traces: { source: "local", items: [] },
    metrics: [
      {
        name: "abk.agent.cost",
        type: "counter",
        attributes: ["role", "source"],
        series: [{ labels: { role: "implement" }, points: [[1767261600, 3.75]] }],
      },
      {
        name: "abk.tick.duration",
        type: "histogram",
        attributes: ["outcome"],
        series: [{ labels: { outcome: "idle" }, points: [[1767261600, 12]] }],
      },
      { name: "abk.units", type: "gauge", attributes: ["state"], series: [] },
    ],
  };
}

function open() {
  render(
    <MemoryRouter initialEntries={["/metrics"]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe("the metrics page", () => {
  it("lists every catalogued metric with its type and attributes", async () => {
    recordedApi().answer("/api/metrics", metrics("prometheus"));
    open();

    for (const [name, type, attribute] of [
      ["abk.agent.cost", "counter", "role"],
      ["abk.tick.duration", "histogram", "outcome"],
      ["abk.units", "gauge", "state"],
    ]) {
      const entry = (await screen.findByText(name)).closest("[data-metric]") as HTMLElement;
      expect(entry).toHaveAttribute("data-metric", name);
      expect(entry).toHaveTextContent(type);
      expect(within(entry).getByText(attribute)).toBeInTheDocument();
    }
  });

  it("says Prometheus drew the charts when it answered", async () => {
    recordedApi().answer("/api/metrics", metrics("prometheus"));
    open();

    expect(await screen.findByTestId("metric-source")).toHaveTextContent(/prometheus/i);
  });

  it("says local files drew the charts when the stores are down", async () => {
    recordedApi().answer("/api/metrics", metrics("local"));
    open();

    expect(await screen.findByTestId("metric-source")).toHaveTextContent(/local files/i);
  });

  it("labels each series of a metric", async () => {
    recordedApi().answer("/api/metrics", {
      ...metrics("prometheus"),
      metrics: [
        {
          name: "abk.agent.tokens",
          type: "counter",
          attributes: ["kind"],
          series: [
            { labels: { kind: "input" }, points: [[1767261600, 10]] },
            { labels: { kind: "output" }, points: [[1767261600, 5]] },
          ],
        },
      ],
    });
    open();

    const found = await screen.findByText("abk.agent.tokens");
    const entry = found.closest("[data-metric]") as HTMLElement;
    expect(within(entry).getByText("kind=input")).toBeInTheDocument();
    expect(within(entry).getByText("kind=output")).toBeInTheDocument();
  });

  it("lists the recent traces and says which store listed them", async () => {
    recordedApi().answer("/api/metrics", {
      ...metrics("prometheus"),
      traces: {
        source: "tempo",
        items: [
          { id: "abc", name: "abk.tick", start: "2026-01-01T10:00:00+00:00", duration_ms: 42 },
        ],
      },
    });
    open();

    expect(await screen.findByTestId("trace-source")).toHaveTextContent(/tempo/i);
    expect(screen.getByText("abk.tick")).toBeInTheDocument();
  });
});
