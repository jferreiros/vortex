import { Fragment, useEffect, useRef, useState } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Placeholder from "../../../components/ui/Placeholder";
import "./insights.css";

const RANGES = [
  { label: "7 días", days: 7 },
  { label: "30 días", days: 30 },
  { label: "90 días", days: 90 },
];

// Mirrors business_insights.RESIDUAL_CANCEL_REASONS: the backend already
// sorts these last regardless of count, this only marks them visually so a
// tall "Otro motivo" bar never reads as the clinic's top cancellation driver.
const RESIDUAL_CANCEL_REASONS = new Set(["other", "unknown"]);

//: Business insights change slowly enough that a 6s poll reads as "live"
// without hammering the log — contrast with the 700ms the per-call zoom
// page polls at in useCallTimeline. The analytics endpoint tails a SQLite
// store, so its poll can run a touch faster at the same cost.
const POLL_MS = 6000;
const ANALYTICS_POLL_MS = 5000;

// Every number on this page comes from GET /api/wall/business-insights,
// which reads calls.jsonl through vortex.observability.business_insights.
// No patient name, DNI or phone ever appears here — only doctors, dates
// and counts, all already-anonymous by the time they leave the API.
//
// The endpoint reports where its events came from (payload.source.kind:
// line_api, cache or jsonl_fallback). A failed poll or a degraded source
// must never render as real zeros — the notice below says so instead.
function useBusinessInsights(days) {
  const [state, setState] = useState({ data: null, failed: false });
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    setState({ data: null, failed: false });

    async function poll() {
      try {
        const res = await fetch(`/api/wall/business-insights?days=${days}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (cancelledRef.current) return;
        setState({ data: json, failed: false });
      } catch {
        // Keep the last good payload if there is one: a dropped request
        // degrades to slightly stale data plus the notice, not an empty page.
        if (!cancelledRef.current) setState((s) => ({ ...s, failed: true }));
      }
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelledRef.current = true;
      clearInterval(interval);
    };
  }, [days]);

  return state;
}

// The call-analytics panels below read GET /api/wall/analytics, which serves
// aggregates off logs/calls.db (a rebuildable projection of calls.jsonl —
// the JSONL stays the source of truth). Until the line emits turn.metrics,
// talk ratio and words-per-turn come from word counts; the payload's
// `metrics` block and each panel's `basis` field say so honestly.
function useAnalytics(days) {
  const [state, setState] = useState({ data: null, failed: false });
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;

    async function poll() {
      try {
        const res = await fetch(`/api/wall/analytics?days=${days}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (cancelledRef.current) return;
        setState({ data: json, failed: false });
      } catch {
        if (!cancelledRef.current) setState((s) => ({ ...s, failed: true }));
      }
    }

    poll();
    const interval = setInterval(poll, ANALYTICS_POLL_MS);
    return () => {
      cancelledRef.current = true;
      clearInterval(interval);
    };
  }, [days]);

  return state;
}

function SourceNotice({ failed, source }) {
  let text = null;
  if (failed) {
    text = "No se pudieron cargar los datos de llamadas en vivo — se reintenta cada pocos segundos.";
  } else if (source?.kind === "cache") {
    text = "La línea no respondió en la última lectura — mostrando la última copia recibida.";
  } else if (source?.kind === "jsonl_fallback") {
    text = "Sin conexión directa con la línea — leyendo el registro de llamadas compartido.";
  }
  if (!text) return null;
  return (
    <div className="insights-notice" role="status">
      {text}
    </div>
  );
}

function ReasonBars({ unavailability }) {
  const buckets = unavailability?.buckets ?? [];
  if (!buckets.length) {
    return <Placeholder kind="chart" ratio="21/6" label="Ninguna llamada se quedó sin cita en este período." />;
  }
  return (
    <div className="reason-bars">
      {buckets.map((b) => (
        <div className="reason-bar-row" key={b.key}>
          <div className="reason-bar-top">
            <span className="reason-bar-label">{b.label}</span>
            <span className="reason-bar-value">
              {b.count} · {b.pct}%
            </span>
          </div>
          <div className="reason-bar-track">
            <div className="reason-bar-fill" style={{ width: `${Math.max(b.share * 100, 4)}%` }} />
          </div>
        </div>
      ))}
    </div>
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
        {service.declined_full > 0
          ? `, ${service.declined_full} rechazadas por no quedar hueco`
          : ""}
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

// Occupancy by service: pick a site (or all of them), see every specialty's
// demand-vs-capacity in one glance, tap a box for the hiring math behind it.
function ServiceOccupancy({ occupancy }) {
  const [site, setSite] = useState("all");
  const [openId, setOpenId] = useState(null);
  const sites = occupancy?.sites ?? [];
  const services = site === "all" ? occupancy?.all ?? [] : sites.find((s) => s.id === site)?.services ?? [];
  const active = services.find((s) => s.id === openId) ?? null;

  return (
    <div className="service-occupancy">
      <div className="insights-range">
        <button
          type="button"
          className={`insights-range-pill ${site === "all" ? "on" : ""}`}
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
            className={`insights-range-pill ${site === s.id ? "on" : ""}`}
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
        <Placeholder kind="diagram" ratio="21/8" label="Sin peticiones de especialidad en este período." />
      )}
    </div>
  );
}

function Heatmap({ view }) {
  const rows = view?.rows ?? [];
  const bands = view?.bands ?? [];
  const open = view?.open;
  const hasDemand = rows.some((r) => r.cells.some((c) => c.demand > 0));
  const hasSupply = rows.some((r) => r.cells.some((c) => c.availability > 0));
  const hasClosed = (open ?? []).some((row) => row.some((o) => o === false));
  if (!hasDemand && !hasSupply && !hasClosed) {
    return (
      <Placeholder kind="diagram" ratio="21/8" label="Sin peticiones con franja horaria en este período." />
    );
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
                  <div
                    key={row.weekday}
                    className="heatmap-cell closed"
                    title={`${row.weekday} · ${band}: cerrado`}
                  >
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
          <i className="heatmap-swatch demand" /> Nº pedidas / ofrecidas
        </span>
        <span>
          <i className="heatmap-swatch gap" /> Demanda sin oferta
        </span>
        <span>
          <i className="heatmap-swatch closed" /> Cerrado
        </span>
      </div>
    </div>
  );
}

function CancelTile({ value, label, sub, tone, highlight }) {
  return (
    <div className={`cancel-tile${highlight ? " rate" : ""}`}>
      <span className={`cancel-value${tone ? ` ${tone}` : ""}`}>{value}</span>
      <span className="cancel-label">{label}</span>
      {sub && <span className="cancel-sub">{sub}</span>}
    </div>
  );
}

//: What became of the slot a cancellation freed, in stack order: another
// call took it, the appointment day arrived with it still empty, or the
// day is still to come. Same tones as the tiles above (good/bad).
const SLOT_DESTINATIONS = [
  { key: "relocated", legend: "Reubicados" },
  { key: "lost", legend: "Perdidos" },
  { key: "pending", legend: "Pendientes" },
];

function CancellationStats({ cancellations }) {
  const c = cancellations ?? {};
  const freedTotal = c.freed_total ?? 0;
  if (!freedTotal) {
    return <Placeholder kind="chart" ratio="4/3" label="No hubo cancelaciones en este período." />;
  }
  const rate = c.cancel_rate ?? {};
  const lead = c.lead_time ?? {};
  return (
    <div className="cancel-stats">
      <div className="cancel-rates">
        <CancelTile
          highlight
          value={rate.pct != null ? `${rate.pct}%` : "—"}
          label="Tasa de cancelación"
          sub={`${rate.cancels ?? 0} cancelaciones entre ${rate.appointments ?? 0} citas tocadas`}
        />
        <CancelTile
          highlight
          value={c.recovery_rate_pct != null ? `${c.recovery_rate_pct}%` : "—"}
          label="Tasa de recuperación"
          sub={`${c.relocated ?? 0} reubicados de ${(c.relocated ?? 0) + (c.lost ?? 0)} huecos decididos`}
        />
      </div>
      {(lead.buckets?.length > 0 || c.reasons?.length > 0) && (
        <div className="cancel-columns">
          {lead.buckets?.length > 0 && (
            <div className="cancel-section">
              <p className="cancel-section-title">Antelación de la cancelación</p>
              <div className="cancel-buckets">
                {lead.buckets.map((b) => {
                  // Each bucket's bar splits by the freed slot's destination —
                  // a per-bucket relocated/lost/pending breakdown in the
                  // payload. Until it carries one, the row falls back to the
                  // plain count fill.
                  const segs = SLOT_DESTINATIONS.map((d) => ({ ...d, n: b[d.key] ?? 0 })).filter(
                    (d) => d.n > 0
                  );
                  const width = Math.max((b.share ?? 0) * 100, b.count ? 4 : 0);
                  return (
                    <div className="cancel-bucket" key={b.key}>
                      <span className="cancel-bucket-label">{b.label}</span>
                      <div className="cancel-bucket-track">
                        {segs.length ? (
                          <div className="cancel-bucket-stack" style={{ width: `${width}%` }}>
                            {segs.map((d) => (
                              <div
                                className={`cancel-bucket-seg ${d.key}`}
                                key={d.key}
                                style={{ flex: d.n }}
                                title={`${d.legend}: ${d.n}`}
                              />
                            ))}
                          </div>
                        ) : (
                          <div className="cancel-bucket-fill" style={{ width: `${width}%` }} />
                        )}
                      </div>
                      <span className="cancel-bucket-count">{b.count}</span>
                    </div>
                  );
                })}
              </div>
              {lead.buckets.some((b) => SLOT_DESTINATIONS.some((d) => (b[d.key] ?? 0) > 0)) && (
                <div className="cancel-legend">
                  {SLOT_DESTINATIONS.map((d) => (
                    <span key={d.key}>
                      <i className={`cancel-swatch ${d.key}`} /> {d.legend}
                    </span>
                  ))}
                </div>
              )}
              <p className="cancel-hint">
                Con cuánto aviso se canceló cada hueco, y qué fue de él — las de última hora son las que se pierden.
              </p>
            </div>
          )}
          {c.reasons?.length > 0 && (
            <div className="cancel-section">
              <p className="cancel-section-title">Motivo dicho al cancelar</p>
              {c.reasons.map((r) => (
                <div
                  className={
                    RESIDUAL_CANCEL_REASONS.has(r.key)
                      ? "cancel-list-row cancel-list-row-residual"
                      : "cancel-list-row"
                  }
                  key={r.key}
                >
                  <span>{r.label}</span>
                  <span className="cancel-list-count">{r.count}</span>
                </div>
              ))}
              <p className="cancel-hint">
                Leído de las palabras del paciente — no es un dato estructurado.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Call analytics — Hamming-style panels off /api/wall/analytics (SQLite store)
 * -------------------------------------------------------------------------*/

const STATUS_LABELS = {
  booked: "Con cita",
  registered: "Alta registrada",
  rescheduled: "Reprogramada",
  cancelled: "Cancelada",
  refused: "Sin cita",
  escalated: "Escalada",
  ended: "Terminada",
  live: "En curso",
};

const INTENT_LABELS = {
  book: "Pedir cita",
  register: "Alta nueva",
  reschedule: "Mover cita",
  cancel: "Cancelar",
  "no-action": "Nada que hacer",
  escalate: "Escalar",
};

const ACTION_LABELS = { ...INTENT_LABELS };

function actionLabel(key) {
  if (key.startsWith("none:")) {
    const outcome = key.slice(5);
    return `sin envío · ${STATUS_LABELS[outcome] || outcome}`;
  }
  return ACTION_LABELS[key] || key;
}

function callTag(callId) {
  const parts = String(callId).split("-");
  return parts[parts.length - 1];
}

function ms(value) {
  if (value == null) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

function StatusMix({ mix }) {
  const rows = mix ?? [];
  if (!rows.length) {
    return <Placeholder kind="chart" ratio="21/6" label="Aún no hay llamadas en este período." />;
  }
  return (
    <div className="reason-bars">
      {rows.map((r) => (
        <div className="reason-bar-row" key={r.key}>
          <div className="reason-bar-top">
            <span className="reason-bar-label">{STATUS_LABELS[r.key] || r.key}</span>
            <span className="reason-bar-value">
              {r.count} · {r.pct}%
            </span>
          </div>
          <div className="reason-bar-track">
            <div
              className={`reason-bar-fill ${r.key === "refused" ? "warn" : ""}`}
              style={{ width: `${Math.max(r.share * 100, 4)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function DurationHistogram({ durations }) {
  const buckets = durations?.buckets ?? [];
  const n = durations?.n ?? 0;
  if (!n) {
    return <Placeholder kind="chart" ratio="21/7" label="Ninguna llamada terminada con duración medida." />;
  }
  return (
    <div className="analytics-histo-wrap">
      <div className="analytics-histo">
        {buckets.map((b) => (
          <div
            className="analytics-histo-col"
            key={b.label}
            title={`${b.label}: ${b.count} llamadas (${b.pct}%)`}
          >
            <div className="analytics-histo-bar">
              <div className="analytics-histo-fill" style={{ height: `${Math.max(b.share * 100, b.count ? 6 : 0)}%` }} />
            </div>
            <span className="analytics-histo-label">{b.label}</span>
          </div>
        ))}
      </div>
      <p className="analytics-caption">
        Mediana {durations.median_s != null ? `${Math.round(durations.median_s)} s` : "—"} · p90{" "}
        {durations.p90_s != null ? `${Math.round(durations.p90_s)} s` : "—"} · {n} llamadas
      </p>
    </div>
  );
}

function TalkRatio({ talkRatio }) {
  const calls = talkRatio?.calls ?? [];
  const overall = talkRatio?.overall;
  if (!calls.length) {
    return <Placeholder kind="chart" ratio="21/8" label="Sin turnos registrados en este período." />;
  }
  const proxy = overall?.basis === "words";
  return (
    <div className="analytics-talk">
      {calls.slice(0, 8).map((c) => (
        <div className="analytics-talk-row" key={c.call_id} title={c.call_id}>
          <span className="analytics-talk-id">{callTag(c.call_id)}</span>
          <div className="analytics-talk-track">
            <div
              className="analytics-talk-seg agent"
              style={{ width: `${c.agent_share * 100}%` }}
              title={`Agente ${(c.agent_share * 100).toFixed(0)}%`}
            />
            <div
              className="analytics-talk-seg caller"
              style={{ width: `${c.caller_share * 100}%` }}
              title={`Quien llama ${(c.caller_share * 100).toFixed(0)}%`}
            />
          </div>
        </div>
      ))}
      <div className="analytics-talk-legend">
        <span>
          <i className="analytics-swatch agent" /> Agente {overall ? `${(overall.agent_share * 100).toFixed(0)}%` : "—"}
        </span>
        <span>
          <i className="analytics-swatch caller" /> Quien llama {overall ? `${(overall.caller_share * 100).toFixed(0)}%` : "—"}
        </span>
      </div>
      {proxy && <p className="analytics-caption">Estimado por recuento de palabras — la línea aún no emite turn.metrics.</p>}
    </div>
  );
}

function WordsPerTurn({ rows }) {
  const bySpeaker = Object.fromEntries((rows ?? []).map((r) => [r.speaker, r]));
  if (!bySpeaker.user && !bySpeaker.assistant) {
    return <Placeholder kind="chart" ratio="4/3" label="Sin turnos registrados en este período." />;
  }
  const proxy = (rows ?? []).some((r) => r.basis === "proxy");
  return (
    <div>
      <div className="analytics-tiles two">
        <div className="analytics-tile">
          <span className="analytics-value">{bySpeaker.user?.avg_words ?? "—"}</span>
          <span className="analytics-label">palabras/turno · quien llama ({bySpeaker.user?.turns ?? 0})</span>
        </div>
        <div className="analytics-tile">
          <span className="analytics-value">{bySpeaker.assistant?.avg_words ?? "—"}</span>
          <span className="analytics-label">palabras/turno · agente ({bySpeaker.assistant?.turns ?? 0})</span>
        </div>
      </div>
      {proxy && <p className="analytics-caption">Contadas sobre el texto del turno.</p>}
    </div>
  );
}

function LatencyPanel({ ttfb, tools }) {
  const rows = tools ?? [];
  const hasTtfb = (ttfb?.n ?? 0) > 0;
  if (!hasTtfb && !rows.length) {
    return <Placeholder kind="chart" ratio="21/8" label="Sin mediciones de latencia en este período." />;
  }
  const biggest = Math.max(1, ...rows.map((r) => r.p95_ms ?? 0));
  return (
    <div className="analytics-latency">
      <div className="analytics-tiles two">
        <div className="analytics-tile">
          <span className="analytics-value">{hasTtfb ? ms(ttfb.p50_ms) : "—"}</span>
          <span className="analytics-label">TTFB p50</span>
        </div>
        <div className="analytics-tile">
          <span className="analytics-value">{hasTtfb ? ms(ttfb.p95_ms) : "—"}</span>
          <span className="analytics-label">TTFB p95</span>
        </div>
      </div>
      {!hasTtfb && (
        <p className="analytics-caption">TTFB sin datos — llega con los eventos turn.metrics.</p>
      )}
      {rows.slice(0, 5).map((r) => (
        <div className="analytics-latency-row" key={r.tool}>
          <div className="reason-bar-top">
            <span className="reason-bar-label">{r.tool}</span>
            <span className="reason-bar-value">
              p50 {ms(r.p50_ms)} · p95 {ms(r.p95_ms)}
              {r.failures ? ` · ${r.failures} fallos` : ""}
            </span>
          </div>
          <div className="reason-bar-track">
            <div className="reason-bar-fill" style={{ width: `${Math.max(((r.p95_ms ?? 0) / biggest) * 100, 4)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function Funnel({ rows }) {
  if (!(rows ?? []).length) {
    return <Placeholder kind="chart" ratio="21/7" label="Sin intenciones clasificadas todavía." />;
  }
  return (
    <div className="analytics-funnel">
      {rows.map((r) => (
        <div className="analytics-funnel-row" key={r.intent ?? "none"}>
          <span className="analytics-funnel-intent">{INTENT_LABELS[r.intent] || "Sin clasificar"}</span>
          <span className="analytics-funnel-count">{r.calls}</span>
          <span className="analytics-funnel-actions">
            {Object.entries(r.by_action).map(([action, n]) => (
              <span className="analytics-funnel-chip" key={action}>
                {actionLabel(action)} ×{n}
              </span>
            ))}
          </span>
        </div>
      ))}
    </div>
  );
}

function CostPanel({ cost }) {
  const points = cost?.points ?? [];
  if (!cost || !cost.metered) {
    return <Placeholder kind="chart" ratio="21/7" label="Ninguna llamada medida por coste en este período." />;
  }
  const biggest = Math.max(...points.map((p) => p.list_eur || 0), 0.00001);
  return (
    <div>
      <div className="analytics-tiles three">
        <div className="analytics-tile">
          <span className="analytics-value">{cost.avg_eur != null ? `€${cost.avg_eur.toFixed(4)}` : "—"}</span>
          <span className="analytics-label">coste medio/llamada</span>
        </div>
        <div className="analytics-tile">
          <span className="analytics-value">{cost.avg_list_eur != null ? `€${cost.avg_list_eur.toFixed(4)}` : "—"}</span>
          <span className="analytics-label">a precio de lista</span>
        </div>
        <div className="analytics-tile">
          <span className="analytics-value">
            {cost.priced}/{cost.metered}
          </span>
          <span className="analytics-label">llamadas tarifadas</span>
        </div>
      </div>
      <div className="analytics-spark">
        {points.slice(-40).map((p) => (
          <div
            className={`analytics-spark-bar ${p.priced ? "" : "partial"}`}
            key={p.call_id}
            style={{ height: `${Math.max((p.list_eur / biggest) * 100, 6)}%` }}
            title={`${p.call_id}: €${p.list_eur.toFixed(4)}${p.priced ? "" : " (parcial)"}`}
          />
        ))}
      </div>
      {cost.unpriced?.length > 0 && (
        <p className="analytics-caption">Sin precio verificado: {cost.unpriced.join(", ")}.</p>
      )}
    </div>
  );
}

export default function Insights() {
  const [days, setDays] = useState(30);
  const [site, setSite] = useState("all");
  const { data, failed } = useBusinessInsights(days);
  const { data: analytics, failed: analyticsFailed } = useAnalytics(days);

  const heatmap = data?.heatmap;
  const siteView = site !== "all" ? heatmap?.sites?.find((s) => s.id === site) : null;
  const heatmapView = {
    rows: siteView?.rows ?? heatmap?.rows,
    bands: heatmap?.bands,
    open: siteView?.open ?? heatmap?.open,
    hoursLabel: siteView?.hours_label ?? null,
  };

  return (
    <div className="insights-page">
      <SectionHeader
        eyebrow="Analítica"
        title="Insights"
        subtitle="Demanda no cubierta, ocupación por servicio y huecos de agenda — derivados de las llamadas reales."
        action={
          <div className="insights-range">
            {RANGES.map((r) => (
              <button
                key={r.days}
                className={`insights-range-pill ${r.days === days ? "on" : ""}`}
                type="button"
                onClick={() => setDays(r.days)}
              >
                {r.label}
              </button>
            ))}
          </div>
        }
      />

      <SourceNotice failed={failed} source={data?.source} />

      <div className="insights-bento">
        <Card padding="lg" className="insights-cell wide">
          <SectionHeader
            eyebrow="Demanda no cubierta"
            title="Motivos de no disponibilidad"
            subtitle={
              data ? `${data.unavailability.unmet_total} llamadas de ${data.calls_considered} no acabaron en cita` : undefined
            }
          />
          <ReasonBars unavailability={data?.unavailability} />
        </Card>

        <Card padding="lg" className="insights-cell wide">
          <SectionHeader
            eyebrow="Agenda"
            title="Ocupación por servicio"
            subtitle="Toca un servicio para ver cuántos médicos más harían falta para atender toda la demanda."
          />
          <ServiceOccupancy occupancy={data?.occupancy} />
        </Card>

        <Card padding="lg" className="insights-cell wide">
          <SectionHeader title="Cancelaciones" />
          <CancellationStats cancellations={data?.cancellations} />
        </Card>

        <Card padding="lg" className="insights-cell wide">
          <SectionHeader
            eyebrow="Agenda"
            title="Horas pico sin horario"
            subtitle="Demanda solicitada frente a huecos realmente ofrecidos, por día y franja."
            action={
              <div className="insights-range">
                <button
                  type="button"
                  className={`insights-range-pill ${site === "all" ? "on" : ""}`}
                  onClick={() => setSite("all")}
                >
                  Todas
                </button>
                {(heatmap?.sites ?? []).map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className={`insights-range-pill ${site === s.id ? "on" : ""}`}
                    onClick={() => setSite(s.id)}
                  >
                    {s.name}
                  </button>
                ))}
              </div>
            }
          />
          <Heatmap view={heatmapView} />
        </Card>
      </div>

      <SectionHeader
        eyebrow="Llamadas"
        title="Rendimiento de llamadas"
        subtitle="Estado, duración, turnos de habla, latencia y coste — leído del registro de llamadas."
      />
      {analyticsFailed && (
        <div className="insights-notice" role="status">
          No se pudieron cargar las métricas de llamadas — se reintenta cada pocos segundos.
        </div>
      )}

      <div className="insights-bento">
        <Card padding="lg" className="insights-cell">
          <SectionHeader
            eyebrow="Resultado"
            title="Estado de las llamadas"
            subtitle={analytics ? `${analytics.calls_considered} llamadas en el período` : undefined}
          />
          <StatusMix mix={analytics?.status_mix} />
        </Card>

        <Card padding="lg" className="insights-cell">
          <SectionHeader eyebrow="Duración" title="Duración de llamada" />
          <DurationHistogram durations={analytics?.durations} />
        </Card>

        <Card padding="lg" className="insights-cell">
          <SectionHeader eyebrow="Conversación" title="Tiempo de habla: agente vs. quien llama" />
          <TalkRatio talkRatio={analytics?.talk_ratio} />
        </Card>

        <Card padding="lg" className="insights-cell">
          <SectionHeader eyebrow="Conversación" title="Palabras por turno" />
          <WordsPerTurn rows={analytics?.words_per_turn} />
        </Card>

        <Card padding="lg" className="insights-cell">
          <SectionHeader eyebrow="Latencia" title="TTFB y herramientas (p50 / p95)" />
          <LatencyPanel ttfb={analytics?.ttfb} tools={analytics?.tool_latency} />
        </Card>

        <Card padding="lg" className="insights-cell">
          <SectionHeader eyebrow="Embudo" title="Intención → acción enviada" />
          <Funnel rows={analytics?.funnel} />
        </Card>

        <Card padding="lg" className="insights-cell wide">
          <SectionHeader eyebrow="Coste" title="Coste por llamada" />
          <CostPanel cost={analytics?.cost} />
        </Card>
      </div>
    </div>
  );
}
