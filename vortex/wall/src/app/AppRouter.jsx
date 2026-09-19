import { BrowserRouter, HashRouter, Routes, Route, Navigate } from "react-router-dom";
import ScrollToTop from "./ScrollToTop";
import PageWipeOverlay from "./PageWipeOverlay";
import Landing from "../pages/landing/Landing";
import ClinicShell from "../pages/clinic/ClinicShell";
import Home from "../pages/clinic/home/Home";
import Settings from "../pages/clinic/settings/Settings";
import AiConfig from "../pages/clinic/ai/AiConfig";
import Insights from "../pages/clinic/insights/Insights";
import Analytics from "../pages/clinic/analytics/Analytics";
import LiveCalls from "../pages/clinic/live-calls/LiveCalls";
import LiveCallDetail from "../pages/clinic/live-calls/LiveCallDetail";
import Agenda from "../pages/clinic/agenda/Agenda";
import Pathways from "../pages/clinic/pathways/Pathways";
import PatientTimeline from "../pages/clinic/patient-timeline/PatientTimeline";
import Patterns from "../pages/clinic/patterns/Patterns";
import PatternsPathways from "../pages/clinic/patterns-pathways/PatternsPathways";

// Hash-based on purpose: this SPA is served by FastAPI from a single
// registered path (/call/{call_id}/zoom — see vortex/observability/live.py)
// that already forwards any id straight to index.html without validation.
// Routing the rest of the app after the "#" means every route below works
// with zero backend changes: the hash never reaches the server. See
// lib/callRoute.js for how a real call_id in that server path becomes the
// hash's initial entry.
export default function AppRouter() {
  // Dev: real paths so http://127.0.0.1:5173/clinic/home works in a normal
  // address bar. Prod stays on HashRouter because FastAPI only serves the
  // SPA from /wall and /call/{id}/zoom.
  const Router = import.meta.env.DEV ? BrowserRouter : HashRouter;
  return (
    <Router>
      <ScrollToTop />
      <PageWipeOverlay />
      <Routes>
        <Route path="/" element={<Landing />} />

        <Route path="/clinic" element={<ClinicShell />}>
          <Route index element={<Navigate to="home" replace />} />
          <Route path="home" element={<Home />} />
          <Route path="doctor" element={<Agenda />} />
          <Route path="agenda" element={<Navigate to="/clinic/doctor" replace />} />
          <Route path="settings" element={<Settings />} />
          <Route path="ai" element={<AiConfig />} />
          <Route path="personalities" element={<Navigate to="/clinic/ai" replace />} />
          <Route path="insights" element={<Insights />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="live-calls" element={<LiveCalls />} />
          <Route path="live-calls/:callId" element={<LiveCallDetail />} />
          <Route path="patterns-pathways" element={<PatternsPathways />} />
          {/* Not in the Sidebar on their own — reachable directly for testing
              each editor in isolation, outside the combined toggle page
              above (which is what "Pathways & Patterns" links to). */}
          <Route path="pathways" element={<Pathways />} />
          <Route path="patient-timeline/:patientId" element={<PatientTimeline />} />
          <Route path="patterns" element={<Patterns />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  );
}
