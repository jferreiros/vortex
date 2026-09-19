import { useNavigate } from "react-router-dom";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import { PLACEHOLDER_CALLS } from "./placeholderCalls";
import "./live-calls.css";

const STATUS_LABEL = { live: "On a call", escalated: "Escalated" };
const DIRECTION_LABEL = { inbound: "Inbound", outbound: "Outbound" };

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
              <span className="live-call-chip">{DIRECTION_LABEL[call.direction]}</span>
              <span className="live-call-phase">{call.phase}</span>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
