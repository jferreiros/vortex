import { NavLink, Outlet } from "react-router-dom";
import Sidebar, { NavIcon } from "./Sidebar";
import VortyDock from "./VortyDock";
import "./clinic-shell.css";

// Persistent app chrome for every Clinic View page (Home, Settings,
// Insights, Calls, and the per-call transcript).
export default function ClinicShell() {
  return (
    <div className="clinic-shell">
      <Sidebar />
      <main className="clinic-shell-content">
        <div className="clinic-shell-tools">
          <NavLink
            to="/clinic/insights"
            className={({ isActive }) => `clinic-shell-tool ${isActive ? "on" : ""}`}
            title="Statistics"
            aria-label="Statistics"
          >
            <NavIcon name="insights" />
          </NavLink>
        </div>
        <Outlet />
      </main>
      <VortyDock />
    </div>
  );
}
