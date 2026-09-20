import { useNavigate } from "react-router-dom";
import Card from "../../../components/ui/Card";
import { PHASE_LABEL, REASON_LABEL, STATUS_LABEL } from "../../../lib/labels";
import { useLiveCalls } from "../live-calls/useLiveCalls";
import "../home/home.css";
import "./calls.css";

function statusLabel(call) {
  if (call.status === "live" || call.duration) {
    return STATUS_LABEL[call.status] || call.status || "En llamada";
  }
  return STATUS_LABEL[call.status] || STATUS_LABEL.refused;
}

function detailLabel(call) {
  if (call.reason) return REASON_LABEL[call.reason] || call.reason;
  return PHASE_LABEL[call.phase] || call.phase || "—";
}

function whenLabel(call) {
  return call.duration || call.time || "—";
}

export default function Calls() {
  const navigate = useNavigate();
  const feed = useLiveCalls();
  const live = (feed.calls ?? []).map((call) => ({ ...call, status: call.status || "live" }));
  const review = [
    ...(feed.escalated ?? []).map((call) => ({ ...call, status: "escalated" })),
    ...(feed.rejected ?? []).map((call) => ({ ...call, status: call.status || "refused" })),
  ];
  const rows = [...live, ...review];

  return (
    <div className="calls-page">
      <header className="home-hero">
        <p className="home-crumb">Clínica Arenal / Calls</p>
        <div className="home-hero-row">
          <h1 className="home-title">Calls</h1>
        </div>
        <p className="home-lead">Live inbound line, then today&apos;s refusals and escalations.</p>
      </header>

      <Card padding="lg" className="calls-panel">
        {rows.length === 0 ? (
          <p className="calls-empty">No calls on the line yet today.</p>
        ) : (
          <table className="calls-table">
            <thead>
              <tr>
                <th>Caller</th>
                <th>Status</th>
                <th>Detail</th>
                <th className="num">When</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((call) => (
                <tr
                  key={`${call.status}-${call.id}`}
                <tr
                  key={`${call.status}-${call.id}`}
                  tabIndex={0}
                  onClick={() => navigate(`/clinic/live-calls/${call.id}`)}
                  onKeyDown={(e) => e.key === "Enter" && navigate(`/clinic/live-calls/${call.id}`)}
                >
                  <td>
                    <span className="calls-name">{call.patient}</span>
                    {call.phone ? <span className="calls-phone">{call.phone}</span> : null}
                  </td>
                  <td>
                    <span className={`calls-status ${call.status === "live" ? "live" : ""}`}>
                      {statusLabel(call)}
                    </span>
                  </td>
                  <td>{detailLabel(call)}</td>
                  <td className="num">{whenLabel(call)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
