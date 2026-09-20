import { Link, Outlet, useLocation } from "react-router-dom";
import Sidebar, { NavIcon } from "./Sidebar";
import VortyDock from "./VortyDock";
import "./clinic-shell.css";

// Call analytics is only reachable from the Calls window: a labeled button
// opens it, and while it's open the same slot turns into a close (X) back
// to Calls — there is no other entry point and no bare icon-only state.
function CallAnalyticsTool() {
  const { pathname } = useLocation();

  if (pathname === "/clinic/analytics") {
    return (
      <Link
        to="/clinic/calls"
        className="clinic-shell-tool"
        title="Close call analytics"
        aria-label="Close call analytics"
      >
        <NavIcon name="close" />
      </Link>
    );
  }

  if (pathname === "/clinic/calls") {
    return (
      <Link to="/clinic/analytics" className="clinic-shell-tool clinic-shell-tool-labeled">
        <NavIcon name="analytics" />
        <span>Call analytics</span>
      </Link>
    );
  }

  return null;
}

// Persistent app chrome for every Clinic View page (Home, Settings,
// Insights, Calls, and the per-call transcript).
export default function ClinicShell() {
  return (
    <div className="clinic-shell">
      <Sidebar />
      <main className="clinic-shell-content">
        <div className="clinic-shell-tools">
          <CallAnalyticsTool />
        </div>
        <Outlet />
      </main>
      <VortyDock />
    </div>
  );
}
