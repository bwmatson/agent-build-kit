import { useState } from "react";
import { Link } from "react-router-dom";

import type { UsageReport, UsageRow } from "./api";
import { unitPath } from "./unitName";
import { useApi } from "./useApi";

const GROUPINGS = ["unit", "change", "node", "role", "model", "repo", "day"];

const UNIT_KEY = /^[\w.-]+\/\d+$/;

function Row({ row, linked }: { row: UsageRow; linked: boolean }) {
  const { calls, input_tokens, output_tokens, cost_usd } = row.measured;
  return (
    <tr>
      <td>
        {linked && UNIT_KEY.test(row.key) ? <Link to={unitPath(row.key)}>{row.key}</Link> : row.key}
      </td>
      <td>{calls}</td>
      <td>{input_tokens ?? "—"}</td>
      <td>{output_tokens ?? "—"}</td>
      <td>{cost_usd === null ? "—" : cost_usd.toFixed(2)}</td>
    </tr>
  );
}

function ReportTable({ report }: { report: UsageReport }) {
  return (
    <table>
      <thead>
        <tr>
          <th>{report.group_by}</th>
          <th>Calls</th>
          <th>Input</th>
          <th>Output</th>
          <th>Cost (USD)</th>
        </tr>
      </thead>
      <tbody>
        {report.rows.map((row) => (
          <Row key={row.key} row={row} linked={report.group_by === "unit"} />
        ))}
      </tbody>
      <tfoot>
        <Row row={{ ...report.total, key: "Total" }} linked={false} />
      </tfoot>
    </table>
  );
}

function Report({ path }: { path: string }) {
  const report = useApi<UsageReport>(path);
  if (report === null) return null;
  return "error" in report ? (
    <p role="alert">{report.error}</p>
  ) : (
    <ReportTable report={report.data} />
  );
}

/** The usage report for a chosen grouping, as the CLI's report builder gives it. */
export function UsageTable() {
  const [by, setBy] = useState("unit");
  return (
    <>
      <label>
        Group by{" "}
        <select value={by} onChange={(event) => setBy(event.target.value)}>
          {GROUPINGS.map((grouping) => (
            <option key={grouping}>{grouping}</option>
          ))}
        </select>
      </label>
      <Report path={`/api/usage?${new URLSearchParams({ by })}`} />
    </>
  );
}

/** One unit's usage by node: the same report, filtered to the unit. */
export function UsageTab({ name }: { name: string }) {
  return <Report path={`/api/usage?${new URLSearchParams({ by: "node", unit: name })}`} />;
}
