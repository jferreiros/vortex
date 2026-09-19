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

function Suggestion({ text }) {
  if (!text) return null;
  return (
    <div className="insights-suggestion">
      <span className="insights-suggestion-icon" aria-hidden="true">
        →
      </span>
      <p>{text}</p>
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

function ProviderRanking({ providers }) {
  const rows = providers?.providers ?? [];
  if (!rows.length) {
    return <Placeholder kind="diagram" ratio="1/1" label="Nadie pidió un médico por nombre en este período." />;
  }
  return (
    <div className="provider-ranking">
      {rows.slice(0, 6).map((r) => (
        <div className="provider-row" key={r.id}>
          <div className="provider-row-top">
            <span className="provider-name">{r.name}</span>
            {r.flagged && <span className="provider-flag">Muy pedido, baja tasa</span>}
          </div>
          <div className="provider-row-meta">
            <span>{r.requests} peticiones</span>
            <span aria-hidden="true">·</span>
            <span>{r.success_rate}% acaba en cita</span>
            {r.median_wait_days != null && (
              <>
                <span aria-hidden="true">·</span>
                <span>{r.median_wait_days}d de espera media</span>
              </>
            )}
          </div>
          <div className="provider-row-track">
            <div
              className={`provider-row-fill ${r.flagged ? "low" : ""}`}
              style={{ width: `${Math.min(r.success_rate, 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function Heatmap({ heatmap }) {
  const rows = heatmap?.rows ?? [];
  const bands = heatmap?.bands ?? [];
  const hasDemand = rows.some((r) => r.cells.some((c) => c.demand > 0));
  if (!hasDemand) {
    return (
      <Placeholder kind="diagram" ratio="21/8" label="Sin peticiones con franja horaria en este período." />
    );
  }
  const max = Math.max(1, ...rows.flatMap((r) => r.cells.map((c) => c.demand)));
  return (
    <div className="heatmap">
      <div className="heatmap-grid" style={{ gridTemplateColumns: `84px repeat(${bands.length}, 1fr)` }}>
        <div className="heatmap-corner" />
        {bands.map((b) => (
          <div className="heatmap-band-label" key={b}>
            {b}
          </div>
        ))}
        {rows.map((row) => (
          <Fragment key={row.weekday}>
            <div className="heatmap-weekday">{row.weekday}</div>
            {row.cells.map((cell) => {
              const intensity = cell.demand / max;
              const gap = cell.demand > 0 && cell.availability === 0;
              return (
                <div
                  key={cell.band}
                  className={`heatmap-cell ${gap ? "gap" : ""}`}
                  style={{ "--intensity": intensity }}
                  title={`${row.weekday} · ${cell.band}: ${cell.demand} pedidas, ${cell.availability} ofrecidas`}
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
      </div>
    </div>
  );
}

function CancellationStats({ cancellations }) {
  const c = cancellations ?? {};
  const freedTotal = c.freed_total ?? 0;
  if (!freedTotal) {
    return <Placeholder kind="chart" ratio="4/3" label="No hubo cancelaciones en este período." />;
  }
  return (
    <div className="cancel-stats">
      <div className="cancel-trio">
        <div className="cancel-tile">
          <span className="cancel-value">{freedTotal}</span>
          <span className="cancel-label">Liberados</span>
        </div>
        <div className="cancel-tile">
          <span className="cancel-value good">{c.relocated ?? 0}</span>
          <span className="cancel-label">Reubicados</span>
        </div>
        <div className="cancel-tile">
          <span className="cancel-value bad">{c.lost ?? 0}</span>
          <span className="cancel-label">Perdidos</span>
        </div>
        <div className="cancel-tile rate">
          <span className="cancel-value">{c.recovery_rate_pct != null ? `${c.recovery_rate_pct}%` : "—"}</span>
          <span className="cancel-label">Tasa de recuperación</span>
        </div>
      </div>
      {c.pending > 0 && (
        <p className="cancel-pending">{c.pending} todavía a la espera de que llegue el día de la cita.</p>
      )}
      {c.daily && c.daily.length > 0 && (
        <div className="cancel-daily">
          {c.daily.map((d) => {
            const total = d.freed || 1;
            return (
              <div
                className="cancel-daily-col"
                key={d.date}
                title={`${d.date}: ${d.freed} liberados, ${d.relocated} reubicados, ${d.lost} perdidos`}
              >
                <div className="cancel-daily-bar">
                  <div
                    className="cancel-daily-seg relocated"
                    style={{ height: `${(d.relocated / total) * 100}%` }}
                  />
                  <div className="cancel-daily-seg lost" style={{ height: `${(d.lost / total) * 100}%` }} />
                </div>
                <span className="cancel-daily-date">{d.date.slice(5)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function Insights() {
  const [days, setDays] = useState(30);
  const { data, failed } = useBusinessInsights(days);

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
          <Suggestion text={data?.unavailability?.suggested_action} />
        </Card>

        <Card padding="lg" className="insights-cell">
          <SectionHeader eyebrow="Demanda por doctor" title="Médicos más pedidos" />
          <ProviderRanking providers={data?.providers} />
          <Suggestion text={data?.providers?.suggested_action} />
        </Card>

        <Card padding="lg" className="insights-cell">
          <SectionHeader eyebrow="Cancelaciones" title="Slots liberados: reubicados vs. perdidos" />
          <CancellationStats cancellations={data?.cancellations} />
          <Suggestion text={data?.cancellations?.suggested_action} />
        </Card>

        <Card padding="lg" className="insights-cell wide">
          <SectionHeader
            eyebrow="Agenda"
            title="Horas pico sin horario"
            subtitle="Demanda solicitada frente a huecos realmente ofrecidos, por día y franja."
          />
          <Heatmap heatmap={data?.heatmap} />
          <Suggestion text={data?.heatmap?.suggested_action} />
        </Card>
      </div>
    </div>
  );
}
