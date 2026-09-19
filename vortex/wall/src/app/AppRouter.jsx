import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import ScrollToTop from "./ScrollToTop";
import Landing from "../pages/landing/Landing";
import ClinicShell from "../pages/clinic/ClinicShell";
import Home from "../pages/clinic/home/Home";
import Settings from "../pages/clinic/settings/Settings";
import AiConfig from "../pages/clinic/ai/AiConfig";
import Insights from "../pages/clinic/insights/Insights";
import LiveCalls from "../pages/clinic/live-calls/LiveCalls";
import LiveCallDetail from "../pages/clinic/live-calls/LiveCallDetail";
import Agenda from "../pages/clinic/agenda/Agenda";

// Hash-based on purpose: this SPA is served by FastAPI from a single
// registered path (/call/{call_id}/zoom — see vortex/observability/live.py)
// that already forwards any id straight to index.html without validation.
// Routing the rest of the app after the "#" means every route below works
// with zero backend changes: the hash never reaches the server. See
// lib/callRoute.js for how a real call_id in that server path becomes the
// hash's initial entry.
export default function AppRouter() {
  return (
    <HashRouter>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<Landing />} />

        {/* Full-bleed, outside ClinicShell's sidebar layout on purpose —
            see the comment in LiveCallDetail.jsx. */}
        <Route path="/clinic/live-calls/:callId" element={<LiveCallDetail />} />

        <Route path="/clinic" element={<ClinicShell />}>
          <Route index element={<Navigate to="home" replace />} />
          <Route path="home" element={<Home />} />
          <Route path="doctor" element={<Agenda />} />
          <Route path="agenda" element={<Navigate to="/clinic/doctor" replace />} />
          <Route path="settings" element={<Settings />} />
          <Route path="ai" element={<AiConfig />} />
          <Route path="personalities" element={<Navigate to="/clinic/ai" replace />} />
          <Route path="insights" element={<Insights />} />
          <Route path="live-calls" element={<LiveCalls />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  );
}
