import { useNavigate } from "react-router-dom";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import "./live-calls.css";

// PLACEHOLDER: live call feed. There is no "list every active call" endpoint
// yet — vortex/observability's API exposes one call's timeline at a time
// (GET /api/wall/timeline/{call_id}). Only the first row uses the real
// scripted demo (call_id "demo") so clicking through actually works end to
// end; the rest are illustrative cards with no live data behind them yet,
// which is exactly what they should look like until that endpoint exists.
const PLACEHOLDER_CALLS = [
  { id: "demo", patient: "Lucía Ruiz López", phase: "Hablando", status: "live", duration: "00:32", language: "Español" },
  { id: "call-2", patient: "Sin identificar", phase: "Escuchando", status: "live", duration: "00:08", language: "Català" },
  { id: "call-3", patient: "Antonio Pérez Gil", phase: "Ejecutando herramienta", status: "live", duration: "01:14", language: "Español" },
  { id: "call-4", patient: "Ana Salas Ferrer", phase: "Escalada", status: "escalated", duration: "02:03", language: "Español" },
];

const STATUS_LABEL = { live: "En llamada", escalated: "Escalada" };

export default function LiveCalls() {
  const navigate = useNavigate();

  return (
    <div className="live-calls-page">
      <SectionHeader
        eyebrow={`${PLACEHOLDER_CALLS.length} activas`}
        title="Live Calls"
        subtitle="Llamadas en curso ahora mismo. Selecciona una para ver el detalle completo."
      />

      <div className="live-calls-grid">
        {PLACEHOLDER_CALLS.map((call) => (
          <Card
            key={call.id}
            padding="lg"
            className="live-call-card"
            role="button"
            tabIndex={0}
            onClick={() => navigate(`/clinic/live-calls/${call.id}`)}
            onKeyDown={(e) => e.key === "Enter" && navigate(`/clinic/live-calls/${call.id}`)}
          >
            <div className="live-call-card-top">
              <span className={`live-call-status-dot ${call.status}`} />
              <span className="live-call-status-label">{STATUS_LABEL[call.status]}</span>
              <span className="live-call-duration mono">{call.duration}</span>
            </div>
            <span className="live-call-patient">{call.patient}</span>
            <div className="live-call-card-bottom">
              <span className="live-call-chip">{call.language}</span>
              <span className="live-call-phase">{call.phase}</span>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
