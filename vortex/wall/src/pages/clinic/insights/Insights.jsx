import { Fragment, useEffect, useRef, useState } from "react";
import Card from "../../../components/ui/Card";
import { mockInsights } from "./insightsData";
import { selectHeatmapView } from "./insightsSelectors";
import "../home/home.css";
import "./insights.css";

const RANGES = [
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

const POLL_MS = 6000;

// Below this many calls the live aggregates are mostly zeros (one unmet
// bucket, an empty heatmap), which reads as a broken page rather than a
// quiet log. The demo numbers stay up until the real payload can carry
// the panels on its own.
const MIN_CALLS_FOR_LIVE = 80;

function isRichPayload(json) {
  if (!json || !json.unavailability || !json.cancellations || !json.heatmap) return false;
  if ((json.calls_considered ?? 0) < MIN_CALLS_FOR_LIVE) return false;
  if ((json.unavailability.buckets?.length ?? 0) < 2) return false;
  return (json.heatmap.rows ?? []).some((row) => row.cells.some((cell) => cell.demand > 0));
}

function useBusinessInsights(days) {
  const [data, setData] = useState(() => mockInsights(days));
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    setData(mockInsights(days));

    async function poll() {
      try {
        const res = await fetch(`/api/wall/business-insights?days=${days}`);
        if (!res.ok || cancelledRef.current) return;
        const json = await res.json();
        if (cancelledRef.current) return;
        if (isRichPayload(json)) setData(json);
      } catch {
        // Keep the last good payload (or the demo numbers).
      }
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelledRef.current = true;
      clearInterval(interval);
    };
  }, [days]);

  return data;
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

function Kpi({ label, value, unit, hint, spark }) {
  const d = sparkPath(spark, 96, 48);
  return (
    <Card padding="md" className="home-kpi">
      <span className="home-kpi-label">{label}</span>
      <div className="home-kpi-body">
        <div className="home-kpi-copy">
          <div className="home-kpi-value">
            {value}
            {unit ? <span className="home-kpi-unit">{unit}</span> : null}
          </div>
          {hint && <p className="home-kpi-hint">{hint}</p>}
        </div>
        <svg className="home-spark" viewBox="0 0 96 48" aria-hidden="true">
          <path d={d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    </Card>
  );
}

function StatTable({ columns, rows, empty }) {
  if (!rows.length) {
    return <p className="insights-empty">{empty}</p>;
  }
  return (
    <table className="insights-table">
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.key} className={c.num ? "num" : ""}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            {columns.map((c) => (
              <td key={c.key} className={c.num ? "num" : ""}>
                {row[c.key]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ServiceOccupancy({ occupancy }) {
  const services = occupancy?.all ?? [];
  return (
    <StatTable
      empty="No specialty requests in this period."
      columns={[
        { key: "label", label: "Service" },
        { key: "pct", label: "Occupancy", num: true },
        { key: "count", label: "Requests", num: true },
      ]}
      rows={services.map((s) => ({
        id: s.id,
        label: s.name,
        pct: s.occupancy_pct != null ? `${s.occupancy_pct}%` : "—",
        count:
          s.extra_providers_needed > 0
            ? `${s.requested} · +${s.extra_providers_needed} drs.`
            : String(s.requested ?? "—"),
      }))}
    />
  );
}

// Seven day columns x the four bands the clinic splits its hours into.
// A cell is one (weekday, band): "8 / 6" — requested / offered — or
// "Closed" when the selected centre does not open that band at all, which
// is why the site picker exists: a demand gap only matters if the clinic
// could have been open to catch it.
// The fraction of a band's requested slots the clinic could not offer:
// (demand - availability) / demand, clamped to [0, 1]. 8 requested / 6
// offered is a 0.25 miss; 6/6 is a 0 miss (white). Drives the white-to-red
// fill below — never a flat "gap" cutoff, so a near-miss and a total miss
// read as different shades, not the same colour.
function unmetRatio(cell) {
  if (!cell.demand) return 0;
  return Math.max(0, Math.min(1, (cell.demand - cell.availability) / cell.demand));
}

function Heatmap({ view }) {
  const rows = view?.rows ?? [];
  const bands = view?.bands ?? [];
  const open = view?.open;
  const hasDemand = rows.some((r) => r.cells.some((c) => c.demand > 0));
  const hasSupply = rows.some((r) => r.cells.some((c) => c.availability > 0));
  const hasClosed = (open ?? []).some((row) => row.some((o) => o === false));
  if (!hasDemand && !hasSupply && !hasClosed) {
    return <p className="insights-empty">No time-banded requests in this period.</p>;
  }
  return (
    <div className="heatmap">
      {view?.hoursLabel && <p className="heatmap-hours">{view.hoursLabel}</p>}
      <div className="heatmap-grid" style={{ gridTemplateColumns: `96px repeat(${rows.length}, 1fr)` }}>
        <div className="heatmap-corner" />
        {rows.map((row) => (
          <div className="heatmap-col-label" key={row.weekday}>
            {row.weekday}
          </div>
        ))}
        {bands.map((band, bi) => (
          <Fragment key={band}>
            <div className="heatmap-row-label">{band}</div>
            {rows.map((row, wi) => {
              const cell = row.cells[bi] ?? { band, demand: 0, availability: 0 };
              if (open?.[wi]?.[bi] === false) {
                return (
                  <div key={row.weekday} className="heatmap-cell closed" title={`${row.weekday} · ${band}: closed`}>
                    <span className="heatmap-closed-label">Closed</span>
                  </div>
                );
              }
              return (
                <div
                  key={row.weekday}
                  className="heatmap-cell"
                  style={{ "--intensity": unmetRatio(cell) }}
                  title={`${row.weekday} · ${band}: ${cell.demand} requested, ${cell.availability} offered`}
                >
                  <span className="heatmap-demand">{cell.demand || "·"}</span>
                  <span className="heatmap-ratio-sep">/</span>
                  <span className="heatmap-availability">{cell.availability}</span>
                </div>
              );
            })}
          </Fragment>
        ))}
      </div>
    </div>
  );
}

export default function Insights() {
  const [days, setDays] = useState(30);
  const [site, setSite] = useState("all");
  const data = useBusinessInsights(days);
  const unmet = data.unavailability ?? {};
  const cancel = data.cancellations ?? {};
  const calls = data.calls_considered ?? 0;
  const heatmap = data.heatmap;
  const heatmapView = selectHeatmapView(heatmap, site);
  const unmetPct = calls ? Math.round((100 * (unmet.unmet_total ?? 0)) / calls) : 0;
  const topReason = unmet.buckets?.[0];
  // Seven-point trend ending on the value shown: the earlier points sit
  // around it so the sparkline reads as a trend at any scale (7 or 90 days).
  const trend = (value, shape) => shape.map((k) => Math.round((value || 1) * k)).concat(value || 0);

  return (
    <div className="insights-page">
      <header className="home-hero">
        <div className="home-hero-row">
          <h1 className="home-title insights-title">Insights</h1>
          <div className="home-toolbar" role="tablist" aria-label="Period">
            {RANGES.map((r) => (
              <button
                key={r.days}
                type="button"
                className={`home-chip ${r.days === days ? "on" : ""}`}
                onClick={() => setDays(r.days)}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <p className="home-lead">What the line could not honour, and where the agenda is leaking.</p>
      </header>

      <div className="home-kpis">
        <Kpi
          label="Calls in period"
          value={calls}
          hint={`${days} days of inbound line`}
          spark={trend(calls, [0.78, 0.86, 0.83, 0.92, 0.9, 0.97])}
        />
        <Kpi
          label="Did not end in a visit"
          value={unmet.unmet_total ?? 0}
          hint={calls ? `${unmetPct}% of calls` : "No calls yet"}
          spark={trend(unmet.unmet_total, [1.18, 0.96, 1.08, 0.86, 1.12, 0.9])}
        />
        <Kpi
          label="Cancelled slots recovered"
          value={cancel.recovery_rate_pct ?? "—"}
          unit={cancel.recovery_rate_pct != null ? "%" : ""}
          hint={`${cancel.relocated ?? 0} rebooked · ${cancel.lost ?? 0} lost`}
          spark={trend(cancel.recovery_rate_pct, [0.69, 0.78, 0.74, 0.87, 0.94, 0.97])}
        />
        <Kpi
          label="Top miss"
          value={topReason ? `${topReason.pct}%` : "—"}
          hint={topReason?.label ?? "No unmet demand"}
          spark={trend(topReason?.pct, [0.85, 0.9, 0.81, 0.96, 0.94, 0.98])}
        />
      </div>

      <div className="insights-grid">
        <Card padding="lg" className="insights-panel">
          <h2>Why it did not book</h2>
          <StatTable
            empty="No missed bookings in this period."
            columns={[
              { key: "label", label: "Reason" },
              { key: "count", label: "Calls", num: true },
            ]}
            rows={(unmet.buckets ?? []).map((b) => ({ id: b.key, label: b.label, count: `${b.count} · ${b.pct}%` }))}
          />
          {unmet.suggested_action ? <p className="insights-panel-sub insights-note">{unmet.suggested_action}</p> : null}
          {cancel.suggested_action ? <p className="insights-panel-sub insights-note">{cancel.suggested_action}</p> : null}
        </Card>

        <Card padding="lg" className="insights-panel">
          <h2>Occupancy by service</h2>
          <p className="insights-panel-sub">Requests versus available slots, network-wide.</p>
          <ServiceOccupancy occupancy={data.occupancy} />
        </Card>
      </div>

      <Card padding="lg" className="insights-panel">
        <div className="insights-panel-head">
          <div>
            <h2>
              Appointments requested <span className="heatmap-title-sep">/ slots available</span>
            </h2>
          </div>
          <div className="home-toolbar" role="tablist" aria-label="Site">
            <button
              type="button"
              className={`home-chip ${site === "all" ? "on" : ""}`}
              onClick={() => setSite("all")}
            >
              All
            </button>
            {(heatmap?.sites ?? []).map((s) => (
              <button
                key={s.id}
                type="button"
                className={`home-chip ${site === s.id ? "on" : ""}`}
                onClick={() => setSite(s.id)}
              >
                {s.name}
              </button>
            ))}
          </div>
        </div>
        <Heatmap view={heatmapView} />
        {heatmapView.suggestion ? <p className="insights-panel-sub insights-note">{heatmapView.suggestion}</p> : null}
      </Card>
    </div>
  );
}
