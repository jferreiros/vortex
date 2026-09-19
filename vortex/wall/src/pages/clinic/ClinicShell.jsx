import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import "./clinic-shell.css";

// Persistent app chrome for every Clinic View page (Home, Settings,
// Insights, Live Calls). The Live Call detail route intentionally lives
// outside this shell — see AppRouter.jsx.
export default function ClinicShell() {
  return (
    <div className="clinic-shell">
      <Sidebar />
      <main className="clinic-shell-content">
        <Outlet />
      </main>
    </div>
  );
}
