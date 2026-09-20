import { useNavigate } from "react-router-dom";
import { useLayoutEffect, useRef, useState } from "react";
import Card from "../../../components/ui/Card";
import { EMPTY_OVERVIEW, useHomeOverview } from "./useHomeOverview";
import useLiveCalls from "../live-calls/useLiveCalls";
import { PHASE_LABEL } from "../../../lib/labels";
import "../live-calls/live-calls.css";
import "./home.css";

const MANAGER_NAME = "HackSpain";

function patientIdFor(call) {
  return typeof call === "object" && call?.patient_id ? call.patient_id : "";
}

function HistoryIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v4h4" />
      <path d="M12 8v4l3 2" />
    </svg>
  );
}

function dayGreeting(now = new Date()) {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Madrid", hour: "numeric", hourCycle: "h23" }).format(now),
  );
  if (hour < 12) return "Good morning";
  if (hour < 19) return "Good afternoon";
  return "Good evening";
}

function FitTitle({ children }) {
  const ref = useRef(null);

  useLayoutEffect(() => {
    const el = ref.current;
    const row = el?.parentElement;
    if (!el || !row) return;

    const fit = () => {
      const toolbar = row.querySelector(".home-toolbar");
      const available = row.clientWidth - (toolbar ? toolbar.offsetWidth + 32 : 0);
      if (available <= 0) return;
      let low = 28;
      let high = 72;
      el.style.fontSize = `${high}px`;
      if (el.scrollWidth <= available) return;
      while (high - low > 0.4) {
        const mid = (low + high) / 2;
        el.style.fontSize = `${mid}px`;
        if (el.scrollWidth <= available) low = mid;
        else high = mid;
      }
      el.style.fontSize = `${low}px`;
    };

    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(row);
    return () => observer.disconnect();
  }, [children]);

  return (
    <h1 ref={ref} className="home-title">
      {children}
    </h1>
  );
}

function sparkPath(values, width, height) {
  if (!values.length) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return values
    .map((value, i) => {
      const x = (i / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - min) / span) * (height - 4) - 2;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

function Sparkline({ values, tone = "ok" }) {
  const width = 96;
  const height = 48;
  const d = sparkPath(values, width, height);
  return (
    <svg className={`home-spark home-spark-${tone}`} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function KpiCard({ label, value, unit, delta, hint, spark, tone }) {
  const up = !delta?.startsWith("−") && !delta?.startsWith("-");
  return (
    <Card padding="md" className="home-kpi">
      <div className="home-kpi-top">
        <span className="home-kpi-label">{label}</span>
        {delta && (
          <span className={`home-kpi-delta ${up ? "up" : "down"}`}>
            {delta}
          </span>
        )}
      </div>
      <div className="home-kpi-body">
        <div className="home-kpi-copy">
          <div className="home-kpi-value">
            {value}
            {unit ? <span className="home-kpi-unit">{unit}</span> : null}
          </div>
          {hint && <p className="home-kpi-hint">{hint}</p>}
        </div>
        <Sparkline values={spark} tone={tone} />
      </div>
    </Card>
  );
}

function DirectionGlyph({ direction }) {
  const inbound = direction === "inbound";
  return (
    <svg className={`home-call-glyph ${direction}`} viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      {inbound ? (
        <path d="M4 5.5v6.5h6.5M4 12 12 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      ) : (
        <path d="M12 10.5V4H5.5M12 4 4 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      )}
    </svg>
  );
}

function initials(name) {
  if (!name || name === "Sin identificar") return "?";
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

export default function Home() {
  const navigate = useNavigate();
  const [liveFilter, setLiveFilter] = useState("all");
  const data = useHomeOverview() ?? EMPTY_OVERVIEW;
  const { calls: liveFeed } = useLiveCalls();
  const today = data.today ?? EMPTY_OVERVIEW.today;
  const moved = today.rescheduled + today.cancelled;
  const liveCalls =
    liveFilter === "all" ? liveFeed : liveFeed.filter((c) => c.direction === liveFilter);
  const openHistory = (call) => {
    const id = patientIdFor(call);
    if (id) navigate(`/clinic/patient-timeline/${id}`);
  };

  const kpis = [
    {
      label: "Appointments booked",
      value: today.booked,
      hint: today.calls ? `${today.calls} calls today` : "No calls",
      delta: "+12%",
      spark: [18, 20, 19, 22, 24, 23, 28],
      tone: "ok",
    },
    {
      label: "Slots moved",
      value: moved,
      hint: `${today.rescheduled} rescheduled · ${today.cancelled} cancelled`,
      delta: "−3%",
      spark: [11, 10, 12, 9, 8, 10, moved],
      tone: "neutral",
    },
    {
      label: "New patients",
      value: today.registered,
      hint: "Registered via the line",
      delta: "+2",
      spark: [3, 4, 3, 5, 4, 5, today.registered],
      tone: "ok",
    },
    {
      label: "Resolved on the line",
      value: today.contained_pct == null ? "—" : today.contained_pct,
      unit: today.contained_pct == null ? "" : "%",
      hint: "Without escalating to a person",
      delta: "+1.4%",
      spark: [78, 80, 81, 79, 84, 85, today.contained_pct || 86],
      tone: "ok",
    },
  ];

  return (
    <div className="home-page">
      <header className="home-hero">
        <div className="home-hero-row">
          <FitTitle>
            {dayGreeting()}, {MANAGER_NAME}
          </FitTitle>
        </div>
        <p className="home-lead">Look at what your agent has done today.</p>
      </header>

      <div className="home-kpis">
        {kpis.map((kpi) => (
          <KpiCard key={kpi.label} {...kpi} />
        ))}
      </div>

      <section className="home-live">
        <div className="home-live-head">
          <h2>Live</h2>
          <div className="home-toolbar" role="tablist" aria-label="Call direction">
            {["all", "inbound", "outbound"].map((id) => (
              <button
                key={id}
                type="button"
                className={`home-chip ${liveFilter === id ? "on" : ""}`}
                onClick={() => setLiveFilter(id)}
              >
                {id === "all" ? "All" : id === "inbound" ? "Inbound" : "Outbound"}
              </button>
            ))}
          </div>
        </div>
        <Card padding="sm" className="home-live-card">
          <ul className="home-call-list">
        {liveCalls.length === 0 ? (
            <li className="home-call-empty">No calls in progress.</li>
          ) : (
            liveCalls.map((call) => (
              <li key={call.id}>
                <div
                  className="home-call-row"
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/clinic/live-calls/${call.id}`)}
                  onKeyDown={(e) => e.key === "Enter" && navigate(`/clinic/live-calls/${call.id}`)}
                >
                  <span className={`home-call-avatar ${call.status}`}>{initials(call.patient)}</span>
                  <span className="home-call-main">
                    <span className="home-call-name">{call.patient}</span>
                    <span className="home-call-meta">
                      <DirectionGlyph direction={call.direction} />
                      {PHASE_LABEL[call.phase] || call.phase}
                      <span className="dot">·</span>
                      {call.phone}
                    </span>
                    {call.lastTurn ? (
                      <span className="home-call-turn">
                        {call.lastRole === "assistant" ? "Vorty: " : ""}
                        {call.lastTurn}
                      </span>
                    ) : null}
                  </span>
                  <span className="home-call-time">{call.duration}</span>
                  <button
                    type="button"
                    className="home-call-history-btn"
                    disabled={!call.patient_id}
                    onClick={(e) => {
                      e.stopPropagation();
                      openHistory(call);
                    }}
                    title={call.patient_id ? "View patient history" : "Unidentified patient"}
                    aria-label={call.patient_id ? "View patient history" : "Unidentified patient"}
                  >
                    <HistoryIcon />
                  </button>
                </div>
              </li>
            ))
          )}
          </ul>
        </Card>
      </section>
    </div>
  );
}
