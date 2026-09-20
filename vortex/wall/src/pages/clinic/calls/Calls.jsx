import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Card from "../../../components/ui/Card";
import { PHASE_LABEL, REASON_LABEL, STATUS_LABEL } from "../../../lib/labels";
import { HistoryIcon } from "../../../lib/icons";
import { useLiveCalls } from "../live-calls/useLiveCalls";
import "../home/home.css";
import "./calls.css";

// /api/wall/live-calls lists the calls in progress first and then every call
// that ended today, newest first. The refused / escalated review tails may
// reach further back than today, so they are appended only when the day's
// list does not already carry that call.
const FILTERS = [
  { id: "all", label: "All", match: () => true },
  { id: "live", label: "Live", match: (c) => c.status === "live" },
  { id: "booked", label: "Booked", match: (c) => c.status === "booked" },
  { id: "changed", label: "Changed", match: (c) => c.status === "rescheduled" || c.status === "cancelled" },
  { id: "registered", label: "Registered", match: (c) => c.status === "registered" },
  { id: "noaction", label: "No action", match: (c) => ["refused", "escalated", "ended"].includes(c.status) },
];

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
  const [filter, setFilter] = useState("all");

  const day = (feed.calls ?? []).map((call) => ({ ...call, status: call.status || "live" }));
  const seen = new Set(day.map((call) => call.id));
  const review = [
    ...(feed.escalated ?? []).map((call) => ({ ...call, status: "escalated" })),
    ...(feed.rejected ?? []).map((call) => ({ ...call, status: call.status || "refused" })),
  ].filter((call) => !seen.has(call.id));
  const rows = [...day, ...review];

  const active = FILTERS.find((f) => f.id === filter) ?? FILTERS[0];
  const shown = rows.filter(active.match);
  const liveCount = rows.filter((c) => c.status === "live").length;
  const open = (id) => navigate(`/clinic/live-calls/${id}`);

  return (
    <div className="calls-page">
      <header className="home-hero">
        <div className="home-hero-row">
          <h1 className="home-title">Call records</h1>
        </div>
        <p className="home-lead">
          Every call the line has handled today, live or closed.
          {rows.length ? ` ${rows.length} calls · ${liveCount} live.` : ""}
        </p>
      </header>

      <div className="home-toolbar calls-filters" role="tablist" aria-label="Call status">
        {FILTERS.map((f) => {
          const n = rows.filter(f.match).length;
          return (
            <button
              key={f.id}
              type="button"
              role="tab"
              aria-selected={filter === f.id}
              className={`home-chip ${filter === f.id ? "on" : ""}`}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
              <span className="calls-chip-count">{n}</span>
            </button>
          );
        })}
      </div>

      <Card padding="lg" className="calls-panel">
        {shown.length === 0 ? (
          <p className="calls-empty">
            {rows.length === 0 ? "No calls on the line yet today." : "No calls match this filter."}
          </p>
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
              {shown.map((call) => (
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
      </Card>
    </div>
  );
}
