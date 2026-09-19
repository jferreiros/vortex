import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import VortyDock from "./VortyDock";
import "./clinic-shell.css";

// Persistent app chrome for every Clinic View page (Home, Settings,
// Insights, Live Calls, and the per-call transcript).
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
