import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Placeholder from "../../../components/ui/Placeholder";
import { MIN_REQUESTS, providerView } from "./providerView";
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
// page polls at in useCallTimeline.
const POLL_MS = 6000;

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

function ProviderDetail({ row }) {
  const reasons = row.unmet_reasons ?? [];
  const elsewhere = row.booked_elsewhere ?? 0;
  const other = row.other_outcomes ?? 0;
  const notBooked = row.requests - row.booked;
  if (!notBooked) {
    return (
      <p className="provider-detail-empty">
        Todas las peticiones de {row.name} acabaron en cita en este período.
      </p>
    );
  }
  return (
    <div className="provider-detail">
      <p className="provider-detail-head">
        {notBooked} de {row.requests} peticiones no acabaron en cita con este médico:
      </p>
      {reasons.map((b) => (
        <div className="provider-detail-row" key={b.key}>
          <span>{b.label}</span>
          <span className="provider-detail-count">{b.count}</span>
        </div>
      ))}
      {elsewhere > 0 && (
        <div className="provider-detail-row">
          <span>{elsewhere === 1 ? "Acabó en cita con otro médico" : "Acabaron en cita con otro médico"}</span>
          <span className="provider-detail-count">{elsewhere}</span>
        </div>
      )}
      {other > 0 && (
        <div className="provider-detail-row">
          <span>Otro desenlace (registro, cancelación o llamada cortada)</span>
          <span className="provider-detail-count">{other}</span>
        </div>
      )}
    </div>
  );
}

// One compact row: name, a mini bar, the stats line and at most one badge.
// Both rankings share it — what changes is which number the bar and the
// stats lead with, and which badge (if any) the row earns.
function ProviderRankRow({ point, barPct, stats, badge, open, onToggle }) {
  return (
    <div className={`provider-row ${open ? "open" : ""}`}>
      <button type="button" className="provider-compact-head" aria-expanded={open} onClick={onToggle}>
        <span className="provider-name">{point.name}</span>
        <span className="provider-compact-bar">
          <span className="provider-row-track">
            <span
              className={`provider-row-fill ${point.flagged ? "low" : ""}`}
              style={{ width: `${barPct}%` }}
            />
          </span>
        </span>
        <span className="provider-compact-meta">{stats}</span>
        {badge}
        <span className="provider-chevron" aria-hidden="true">›</span>
      </button>
      {open && <ProviderDetail row={point.row} />}
    </div>
  );
}

function fmtWait(p) {
  return p.waitDays != null ? ` · ${p.waitDays}d` : "";
}

// Two rankings, one dataset: who gets asked for the most, and who turns
// the most of those requests into a kept appointment. A doctor can chart
// in both — that overlap is the story, not a bug.
function ProviderRankings({ providers }) {
  const [openKey, setOpenKey] = useState(null);
  const view = useMemo(() => providerView(providers), [providers]);
  if (!view.hasData) {
    return <Placeholder kind="diagram" ratio="1/1" label="Nadie pidió un médico por nombre en este período." />;
  }
  const toggle = (key) => setOpenKey((k) => (k === key ? null : key));
  return (
    <div className="provider-rankings-wrap">
      <div className="provider-rankings">
        <section className="provider-rank">
          <p className="provider-rank-title">Los más pedidos</p>
          <p className="provider-rank-sub">Top 5 por peticiones</p>
          <div className="provider-rank-rows">
            {view.mostRequested.map((p) => {
              const key = `req:${p.id}`;
              return (
                <ProviderRankRow
                  key={p.id}
                  point={p}
                  barPct={view.maxRequests ? Math.max((p.requests / view.maxRequests) * 100, 6) : 0}
                  stats={`${p.requests} pet · ${p.successRate}%${fmtWait(p)}`}
                  badge={p.flagged ? <span className="provider-flag">Baja tasa</span> : null}
                  open={openKey === key}
                  onToggle={() => toggle(key)}
                />
              );
            })}
          </div>
        </section>
        <section className="provider-rank">
          <p className="provider-rank-title">Los que más citan</p>
          <p className="provider-rank-sub">Top 5 por % de cierre · mín. 2 peticiones</p>
          {view.topClosers.length > 0 ? (
            <div className="provider-rank-rows">
              {view.topClosers.map((p) => {
                const key = `close:${p.id}`;
                return (
                  <ProviderRankRow
                    key={p.id}
                    point={p}
                    barPct={Math.min(Math.max(p.successRate, p.successRate > 0 ? 4 : 0), 100)}
                    stats={`${p.successRate}% · ${p.requests} pet${fmtWait(p)}`}
                    badge={
                      p.id === view.referenciaId ? (
                        <span className="provider-flag bench">Referencia</span>
                      ) : null
                    }
                    open={openKey === key}
                    onToggle={() => toggle(key)}
                  />
                );
              })}
            </div>
          ) : (
            <p className="provider-rank-empty">
              Volumen insuficiente: ningún médico llega a {MIN_REQUESTS} peticiones en este período.
            </p>
          )}
        </section>
      </div>
      {view.clinicRate != null && (
        <p className="provider-avg">
          Media de la clínica: <strong>{view.clinicRate}%</strong> de las peticiones acaban en cita.
        </p>
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
      {(c.reasons?.length > 0 || c.by_provider?.length > 0) && (
        <div className="cancel-columns">
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
          {c.by_provider?.length > 0 && (
            <div className="cancel-section">
              <p className="cancel-section-title">Médicos con más huecos liberados</p>
              {c.by_provider.map((p) => (
                <div className="cancel-list-row" key={p.id}>
                  <span>{p.name}</span>
                  <span className="cancel-list-count">
                    {p.freed} liberados{p.lost ? ` · ${p.lost} perdidos` : ""}
                  </span>
                </div>
              ))}
              <p className="cancel-hint">Dónde se concentra la agenda que hay que rescatar.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Insights() {
  const [days, setDays] = useState(30);
  const [site, setSite] = useState("all");
  const { data, failed } = useBusinessInsights(days);

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
        subtitle="Demanda no cubierta, médicos más pedidos y huecos de agenda — derivados de las llamadas reales."
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
            eyebrow="Demanda por doctor"
            title="Los más pedidos y los que más citan"
            subtitle="Toca un médico para ver por qué no cerraron sus citas."
          />
          <ProviderRankings providers={data?.providers} />
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
    </div>
  );
}
