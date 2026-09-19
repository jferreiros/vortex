import { Fragment, useEffect, useRef, useState } from "react";
import Card from "../../../components/ui/Card";
import { MOCK_STATS } from "./insightsData";
import { selectHeatmapView, selectServices } from "./insightsSelectors";
import "../home/home.css";
import "./insights.css";

const RANGES = [
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

const POLL_MS = 6000;

function isStatsPayload(json) {
  return Boolean(json && json.unavailability && json.cancellations);
}

function useBusinessInsights(days) {
  const [data, setData] = useState(MOCK_STATS);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;

    async function poll() {
      try {
        const res = await fetch(`/api/wall/business-insights?days=${days}`);
        if (!res.ok || cancelledRef.current) return;
        const json = await res.json();
        if (cancelledRef.current) return;
        if (isStatsPayload(json) && (json.unavailability.unmet_total || json.calls_considered)) {
          setData(json);
        }
      } catch {
        // Keep the last good payload (or the mock).
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

// One box per specialty: name, occupancy % (can read over 100% — the
// platform only offers a slot that exists, so unmatched demand is a real
// rejection for being full), a capped mini-bar and the volume behind it.
function ServiceTile({ service, active, onClick }) {
  const pct = service.occupancy_pct;
  const known = pct != null;
  const over = known && pct > 100;
  return (
    <button
      type="button"
      className={`service-tile ${over ? "over" : ""} ${active ? "active" : ""}`}
      aria-expanded={active}
      onClick={onClick}
    >
      <div className="service-tile-top">
        <span className="service-tile-name">{service.name}</span>
        <span className={`service-tile-pct ${over ? "over" : ""}`}>{known ? `${pct}%` : "—"}</span>
      </div>
      <span className="service-tile-track">
        <span
          className={`service-tile-fill ${over ? "over" : ""}`}
          style={{ width: `${known ? Math.min(pct, 100) : 0}%` }}
        />
      </span>
      <span className="service-tile-meta">
        {service.requested} pet · {service.providers} médico{service.providers === 1 ? "" : "s"}
      </span>
    </button>
  );
}

// What tapping a tile answers: how many more providers of that specialty
// would have absorbed every request this period, at today's slots-per-doctor
// rate — the number business_insights.service_occupancy already computed.
function ServiceDetail({ service }) {
  const pct = service.occupancy_pct;
  const extra = service.extra_providers_needed ?? 0;
  if (pct == null) {
    return (
      <p className="service-detail-empty">
        {service.name}: se pidió cita pero no quedó registrado ningún hueco ofrecido — no se
        puede calcular la ocupación en este período.
      </p>
    );
  }
  if (extra <= 0) {
    return (
      <p className="service-detail-empty">
        {service.name} tiene margen: {service.providers} médico{service.providers === 1 ? "" : "s"}{" "}
        cubren la demanda pedida ({pct}%).
      </p>
    );
  }
  return (
    <div className="service-detail">
      <p className="service-detail-head">
        {service.name}: {service.requested} peticiones contra {service.offered} huecos ofrecidos
        ({pct}% de ocupación)
        {service.declined_full > 0 ? `, ${service.declined_full} rechazadas por no quedar hueco` : ""}
        .
      </p>
      <p className="service-detail-calc">
        Con <strong>{extra} médico{extra === 1 ? "" : "s"} más</strong> de esta especialidad
        (sobre los {service.providers} actuales) se habría podido atender a todos los que la
        pidieron.
      </p>
    </div>
  );
}

// Ocupación por servicio: pick a centre (or all of them), see every
// specialty's demand-vs-capacity in one glance, tap a box for the hiring
// math behind it. Data comes precomputed in the same business-insights
// payload as the rest of the page — no calculation duplicated here.
function ServiceOccupancy({ occupancy }) {
  const [site, setSite] = useState("all");
  const [openId, setOpenId] = useState(null);
  const sites = occupancy?.sites ?? [];
  const services = selectServices(occupancy, site);
  const active = services.find((s) => s.id === openId) ?? null;

  return (
    <div className="service-occupancy">
      <div className="home-toolbar" role="tablist" aria-label="Centro">
        <button
          type="button"
          className={`home-chip ${site === "all" ? "on" : ""}`}
          onClick={() => {
            setSite("all");
            setOpenId(null);
          }}
        >
          Todos los centros
        </button>
        {sites.map((s) => (
          <button
            key={s.id}
            type="button"
            className={`home-chip ${site === s.id ? "on" : ""}`}
            onClick={() => {
              setSite(s.id);
              setOpenId(null);
            }}
          >
            {s.name}
          </button>
        ))}
      </div>
      {services.length ? (
        <>
          <div className="service-grid">
            {services.map((s) => (
              <ServiceTile
                key={s.id}
                service={s}
                active={openId === s.id}
                onClick={() => setOpenId(openId === s.id ? null : s.id)}
              />
            ))}
          </div>
          {active && <ServiceDetail service={active} />}
        </>
      ) : (
        <p className="insights-empty">Sin peticiones de especialidad en este período.</p>
      )}
    </div>
  );
}

// Seven day columns x the four bands the clinic splits its hours into.
// A cell is one (weekday, band): pedidas on top, ofrecidas underneath —
// or "Cerrado" when the selected centre does not open that band at all,
// which is why the site picker exists: a demand gap only matters if the
// clinic could have been open to catch it.
function Heatmap({ view }) {
  const rows = view?.rows ?? [];
  const bands = view?.bands ?? [];
  const open = view?.open;
  const hasDemand = rows.some((r) => r.cells.some((c) => c.demand > 0));
  const hasSupply = rows.some((r) => r.cells.some((c) => c.availability > 0));
  const hasClosed = (open ?? []).some((row) => row.some((o) => o === false));
  if (!hasDemand && !hasSupply && !hasClosed) {
    return <p className="insights-empty">Sin peticiones con franja horaria en este período.</p>;
  }
  const max = Math.max(1, ...rows.flatMap((r) => r.cells.map((c) => c.demand)));
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
                  <div key={row.weekday} className="heatmap-cell closed" title={`${row.weekday} · ${band}: cerrado`}>
                    <span className="heatmap-closed-label">Cerrado</span>
                  </div>
                );
              }
              const intensity = cell.demand / max;
              const gap = cell.demand > 0 && cell.availability === 0;
              return (
                <div
                  key={row.weekday}
                  className={`heatmap-cell ${gap ? "gap" : ""}`}
                  style={{ "--intensity": intensity }}
                  title={`${row.weekday} · ${band}: ${cell.demand} pedidas, ${cell.availability} ofrecidas`}
                >
                  <span className="heatmap-demand">{cell.demand || "·"}</span>
                  <span className="heatmap-availability">{cell.availability}</span>
                </div>
              );
            })}
          </Fragment>
        ))}
      </div>
      <div className="heatmap-legend">
        <span>
          <i className="heatmap-swatch demand" /> N pedidas / ofrecidas
        </span>
        <span>
          <i className="heatmap-swatch gap" /> Demanda sin oferta
        </span>
        <span>
          <i className="heatmap-swatch closed" /> Cerrado
        </span>
      </div>
      {view?.suggestion && <p className="insights-footnote">{view.suggestion}</p>}
    </div>
  );
}

export default function Insights() {
  const [days, setDays] = useState(30);
  const [site, setSite] = useState("all");
  const data = useBusinessInsights(days) ?? MOCK_STATS;
  const unmet = data.unavailability ?? {};
  const cancel = data.cancellations ?? {};
  const calls = data.calls_considered ?? 0;
  const heatmap = data.heatmap;
  const heatmapView = selectHeatmapView(heatmap, site);
  const unmetPct = calls ? Math.round((100 * (unmet.unmet_total ?? 0)) / calls) : 0;
  const topReason = unmet.buckets?.[0];

  return (
    <div className="insights-page">
      <header className="home-hero">
        <p className="home-crumb">Clínica Arenal / Insights</p>
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
          spark={[160, 178, 170, 190, 188, 200, calls || 214]}
        />
        <Kpi
          label="Did not end in a visit"
          value={unmet.unmet_total ?? 0}
          hint={calls ? `${unmetPct}% of calls` : "No calls yet"}
          spark={[22, 18, 20, 16, 21, 17, unmet.unmet_total || 19]}
        />
        <Kpi
          label="Cancelled slots recovered"
          value={cancel.recovery_rate_pct ?? "—"}
          unit={cancel.recovery_rate_pct != null ? "%" : ""}
          hint={`${cancel.relocated ?? 0} rebooked · ${cancel.lost ?? 0} lost`}
          spark={[48, 55, 52, 61, 66, 68, cancel.recovery_rate_pct || 70]}
        />
        <Kpi
          label="Top miss"
          value={topReason ? `${topReason.pct}%` : "—"}
          hint={topReason?.label ?? "No unmet demand"}
          spark={[40, 42, 38, 45, 44, 46, topReason?.pct || 47]}
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
        </Card>

        <Card padding="lg" className="insights-panel">
          <h2>Ocupación por servicio</h2>
          <p className="insights-panel-sub">
            Toca un servicio para ver cuantos médicos más harían falta para atender toda la demanda.
          </p>
          <ServiceOccupancy occupancy={data.occupancy} />
        </Card>
      </div>

      <Card padding="lg" className="insights-panel">
        <div className="insights-panel-head">
          <div>
            <h2>Horas pico sin horario</h2>
            <p className="insights-panel-sub">
              Demanda solicitada frente a huecos realmente ofrecidos, por día y franja.
            </p>
          </div>
          <div className="home-toolbar" role="tablist" aria-label="Centro">
            <button
              type="button"
              className={`home-chip ${site === "all" ? "on" : ""}`}
              onClick={() => setSite("all")}
            >
              Todas
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
      </Card>

      <Card padding="lg" className="insights-panel">
        <h2>Cancelled slots</h2>
        {cancel.daily?.length ? (
          <StatTable
            empty="No cancellations freed a slot in this period."
            columns={[
              { key: "date", label: "Day" },
              { key: "freed", label: "Freed", num: true },
              { key: "relocated", label: "Rebooked", num: true },
              { key: "lost", label: "Lost", num: true },
            ]}
            rows={cancel.daily.map((d) => ({
              id: d.date,
              date: d.date,
              freed: d.freed,
              relocated: d.relocated,
              lost: d.lost,
            }))}
          />
        ) : (
          <p className="insights-empty">
            {(cancel.freed_total ?? 0) > 0
              ? `${cancel.relocated ?? 0} rebooked, ${cancel.lost ?? 0} lost, ${cancel.pending ?? 0} still pending — too few days to chart.`
              : "No cancellations freed a slot in this period."}
          </p>
        )}
      </Card>
    </div>
  );
}
