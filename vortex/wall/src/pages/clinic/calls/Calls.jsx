import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Card from "../../../components/ui/Card";
import { PHASE_LABEL, REASON_LABEL, STATUS_LABEL } from "../../../lib/labels";
import { HistoryIcon } from "../../../lib/icons";
import { useLiveCalls } from "../live-calls/useLiveCalls";
import "../home/home.css";
import "./calls.css";

const OUTBOUND_POLL_MS = 15000;

function useScheduledOutboundCalls() {
  const [calls, setCalls] = useState([]);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;

    async function poll() {
      try {
        const res = await fetch("/api/wall/scheduled-outbound-calls");
        if (!res.ok || cancelled.current) return;
        const json = await res.json();
        if (cancelled.current) return;
        setCalls(Array.isArray(json?.calls) ? json.calls : []);
      } catch {
        // Keep the last good list.
      }
    }

    poll();
    const interval = setInterval(poll, OUTBOUND_POLL_MS);
    return () => {
      cancelled.current = true;
      clearInterval(interval);
    };
  }, []);

  return calls;
}

function statusLabel(call) {
  return STATUS_LABEL[call.status] || call.status || "On call";
}

function detailLabel(call) {
  if (call.reason) return REASON_LABEL[call.reason] || call.reason;
  return PHASE_LABEL[call.phase] || call.phase || "—";
}

function clockLabel(time) {
  if (!time || time === "—") return "—";
  return time.length >= 5 ? time.slice(0, 5) : time;
}

export default function Calls() {
  const navigate = useNavigate();
  const feed = useLiveCalls();
  const outbound = useScheduledOutboundCalls();

  // /api/wall/live-calls lists the calls in progress first and then every call
  // that ended today, newest first. The refused / escalated review tails may
  // reach further back than today, so they are appended only when the day's
  // list does not already carry that call.
  const day = (feed.calls ?? []).map((call) => ({ ...call, status: call.status || "live" }));
  const seen = new Set(day.map((call) => call.id));
  const review = [
    ...(feed.escalated ?? []).map((call) => ({ ...call, status: "escalated" })),
    ...(feed.rejected ?? []).map((call) => ({ ...call, status: call.status || "refused" })),
  ].filter((call) => !seen.has(call.id));
  const rows = [...day, ...review];
  const open = (id) => navigate(`/clinic/live-calls/${id}`);

  return (
    <div className="calls-page">
      <header className="home-hero">
        <div className="home-hero-row">
          <h1 className="home-title">Call records</h1>
        </div>
      </header>

      <div className="calls-panes">
        <div className="calls-pane">
          <span className="calls-pane-label">Calls handled today</span>
          <Card padding="lg" className="calls-panel calls-panel-primary">
            <div className="calls-panel-body">
              {rows.length === 0 ? (
                <p className="calls-empty">No calls on the line yet today.</p>
              ) : (
                <table className="calls-table">
                  <thead>
                    <tr>
                      <th>Caller</th>
                      <th>Status</th>
                      <th>Detail</th>
                      <th className="num">Time</th>
                      <th className="num">Length</th>
                      <th className="num calls-history-col" aria-hidden="true" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((call) => (
                      <tr
                        key={`${call.status}-${call.id}`}
                        tabIndex={0}
                        onClick={() => open(call.id)}
                        onKeyDown={(e) => e.key === "Enter" && open(call.id)}
                      >
                        <td>
                          <span className="calls-name">{call.patient}</span>
                          {call.phone ? (
                            <span className="calls-phone">
                              {call.direction === "outbound" ? "↗ " : "↙ "}
                              {call.phone}
                            </span>
                          ) : null}
                        </td>
                        <td>
                          <span className={`calls-status ${call.status === "live" ? "live" : ""}`}>
                            {statusLabel(call)}
                          </span>
                        </td>
                        <td>{detailLabel(call)}</td>
                        <td className="num">{clockLabel(call.time)}</td>
                        <td className="num">{call.duration || "—"}</td>
                        <td className="num calls-history-col">
                          <button
                            type="button"
                            className="calls-history-btn"
                            aria-label="View history"
                            title="View history"
                            onClick={(e) => {
                              e.stopPropagation();
                              open(call.id);
                            }}
                          >
                            <HistoryIcon size={16} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </Card>
        </div>

        <div className="calls-pane">
          <span className="calls-pane-label">Scheduled outbound calls</span>
          <Card padding="lg" className="calls-panel calls-panel-secondary">
            <div className="calls-panel-body">
              {outbound.length === 0 ? (
                <p className="calls-empty">No outbound calls scheduled.</p>
              ) : (
                <table className="calls-table">
                  <thead>
                    <tr>
                      <th>Patient</th>
                      <th>Reason</th>
                      <th className="num">When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {outbound.map((call) => (
                      <tr key={call.id}>
                        <td>
                          <span className="calls-name">{call.patient}</span>
                          {call.phone ? <span className="calls-phone">{call.phone}</span> : null}
                        </td>
                        <td>{call.reason || "—"}</td>
                        <td className="num">{call.when || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
