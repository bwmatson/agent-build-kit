import type { ReactElement } from "react";
import { Link, Route, Routes } from "react-router-dom";

import { MetricsPage } from "./metrics";
import { Overview, UnitPage, UsagePage } from "./pages";

/** The shell and its routes: the overview at `/`, a unit at `/units/<change>/<n>`
 * and the usage report at `/usage`. The caller supplies the router. */
export function AppRoutes(): ReactElement {
  return (
    <div className="shell">
      <nav aria-label="Pages">
        <Link to="/">Pipeline</Link> <Link to="/usage">Usage</Link>{" "}
        <Link to="/metrics">Metrics</Link>
      </nav>
      <div className="column">
        <header>abk</header>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/units/:change/:number" element={<UnitPage />} />
          <Route path="/usage" element={<UsagePage />} />
          <Route path="/metrics" element={<MetricsPage />} />
        </Routes>
      </div>
      <aside aria-label="Chat">Chat arrives with sessions.</aside>
    </div>
  );
}
