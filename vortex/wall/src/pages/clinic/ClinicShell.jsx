import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import VortyDock from "./VortyDock";
import "./clinic-shell.css";

// Persistent app chrome for every Clinic View page (Home, Settings,
// Insights, Calls, and the per-call transcript). Statistics live only under
// Analytics in the sidebar — no floating shortcut on every page.
export default function ClinicShell() {
  return (
    <div className="clinic-shell">
      <Sidebar />
      <main className="clinic-shell-content">
        <Outlet />
      </main>
      <VortyDock />
    </div>
  );
}
