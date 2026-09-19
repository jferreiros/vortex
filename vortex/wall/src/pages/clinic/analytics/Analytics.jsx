import { useEffect, useRef, useState } from "react";
import Card from "../../../components/ui/Card";
import Sankey from "./Sankey";
import "../home/home.css";
import "../insights/insights.css";
import "./analytics.css";

const RANGES = [
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

// The endpoint caches for two minutes (ANALYTICS_CACHE_TTL_S), so polling
// faster than that only costs requests and buys nothing.
const POLL_MS = 60000;

const NUM = new Intl.NumberFormat("es-ES");
const num = (value) => (value === null || value === undefined ? "—" : NUM.format(value));

function ms(value) {
  if (value === null || value === undefined) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2).replace(".", ",")} s`;
  return `${Math.round(value)} ms`;
}

function secs(value) {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(2).replace(".", ",")} s`;
}

// _load_events reports where the window came from, as {kind, events, calls}.
const SOURCE_LABEL = {
  supabase: "registro alojado en Supabase",
  line: "la línea en directo",
  jsonl: "el fichero local del contenedor",
};

const LANGUAGE_NAMES = { es: "Español", en: "Inglés", ca: "Catalán", gl: "Gallego", eu: "Euskera" };

/* The page polls its own endpoint. No mock seed: an empty window must read
   as empty, not as a plausible-looking invention — this page's whole claim
   is that every number on it came off a real call. */
function useAnalytics(days) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    setState((prev) => ({ ...prev, loading: !prev.data }));

    async function poll() {
      try {
        const response = await fetch(`/api/wall/analytics?days=${days}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const json = await response.json();
        if (cancelled.current || !json || !json.funnel) return;
        setState({ data: json, error: null, loading: false });
      } catch (error) {
        if (cancelled.current) return;
        // Keep the last good payload on screen and say the feed is stale,
        // rather than blanking a dashboard someone is reading.
        setState((prev) => ({ ...prev, error: String(error.message || error), loading: false }));
      }
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelled.current = true;
      clearInterval(interval);
    };
  }, [days]);

  return state;
}

function Kpi({ label, value, caption }) {
  return (
    <Card padding="md" className="analytics-kpi">
      <span className="analytics-kpi-label">{label}</span>
      <div className="analytics-kpi-value">{value}</div>
      <p className="analytics-kpi-caption">{caption}</p>
    </Card>
  );
}

function Bars({ rows, tone = "primary" }) {
  const max = Math.max(...rows.map((row) => row.count), 1);
  return (
    <ul className="analytics-bars">
      {rows.map((row) => (
        <li key={row.label}>
          <span className="analytics-bars-label">{row.label}</span>
          <span className="analytics-bars-track">
            <span
              className={`analytics-bars-fill tone-${tone}`}
              style={{ width: `${(row.count / max) * 100}%` }}
            />
          </span>
          <span className="analytics-bars-value">
            {num(row.count)}
            <em>{row.pct}%</em>
          </span>
        </li>
      ))}
    </ul>
  );
}

function Stat({ label, value, sub }) {
  return (
    <div className="analytics-stat">
      <span className="analytics-stat-label">{label}</span>
      <strong className="analytics-stat-value">{value}</strong>
      {sub ? <span className="analytics-stat-sub">{sub}</span> : null}
    </div>
  );
}

function TalkSplit({ conversation }) {
  const agent = conversation.agent_share_pct;
  return (
    <div className="analytics-split">
      <div className="analytics-split-bar">
        <span className="analytics-split-agent" style={{ width: `${agent}%` }}>
          <em>{agent}%</em>
        </span>
        <span className="analytics-split-caller" style={{ width: `${(100 - agent).toFixed(1)}%` }}>
          <em>{(100 - agent).toFixed(1)}%</em>
        </span>
      </div>
      <div className="analytics-split-keys">
        <span>
          <i className="dot-agent" /> Agente · {num(conversation.words_agent)} palabras en{" "}
          {num(conversation.turns_agent)} turnos
        </span>
        <span>
          <i className="dot-caller" /> Paciente · {num(conversation.words_user)} palabras en{" "}
          {num(conversation.turns_user)} turnos
        </span>
      </div>
    </div>
  );
}

function CallTable({ rows }) {
  if (!rows.length) return <p className="analytics-empty">Sin llamadas en el periodo.</p>;
  return (
    <div className="analytics-scroll">
      <table className="analytics-table">
        <thead>
          <tr>
            <th>Hora</th>
            <th>Llamada</th>
            <th>Desenlace</th>
            <th>Idioma</th>
            <th className="num">Dur.</th>
            <th className="num">Turnos</th>
            <th className="num">Agente</th>
            <th className="num">Respuesta</th>
            <th className="num">Voz</th>
            <th className="num">Tools</th>
            <th>Motivo</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.call_id}>
              <td className="mono">
                {row.started_at
                  ? new Date(row.started_at).toLocaleTimeString("es-ES", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "—"}
              </td>
              <td className="mono analytics-id" title={row.call_id}>
                {row.call_id.slice(0, 8)}
              </td>
              <td>
                <span className={`analytics-pill tone-${row.group}`}>{row.status_label}</span>
              </td>
              <td>{LANGUAGE_NAMES[row.language] || row.language || "—"}</td>
              <td className="num mono">{row.duration_s ? `${Math.round(row.duration_s)} s` : "—"}</td>
              <td className="num mono">{row.turns}</td>
              <td className="num mono">{row.turns ? `${row.agent_share_pct}%` : "—"}</td>
              <td className="num mono">{ms(row.reply_ms)}</td>
              <td className="num mono">{secs(row.voice_reply_s)}</td>
              <td className="num mono">
                {row.tools}
                {row.tool_failures ? <em className="analytics-fail">+{row.tool_failures}</em> : null}
              </td>
              <td className="analytics-reason">{row.reason ? row.reason.replace(/_/g, " ") : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* Loading skeleton — traces the shipped layout (header, funnel card, the
   8 KPIs, the 4 panels, the table) instead of one centered line of text.
   Every card reuses the real section's classes, so sizes match exactly and
   nothing jumps when the payload lands. Decorative only: the one thing a
   screen reader announces is the status line below, everything else is
   aria-hidden. */
function SkelLine({ width, size = "md", className = "" }) {
  return (
    <span
      className={`analytics-skel-line analytics-skel-line-${size} ${className}`}
      style={{ width }}
    />
  );
}

function SkelPanelHead() {
  return (
    <div className="analytics-panel-head">
      <SkelLine width="55%" size="lg" />
      <SkelLine width="80%" size="sm" className="analytics-skel-gap" />
    </div>
  );
}

function AnalyticsSkeleton() {
  return (
    <div className="analytics-page" aria-busy="true">
      <span className="analytics-sr-only" role="status">
        Leyendo el registro de llamadas…
      </span>
      <div className="analytics-skeleton" aria-hidden="true">
        <header className="home-hero">
          <SkelLine width="180px" size="sm" />
          <div className="home-hero-row">
            <SkelLine width="220px" size="xl" />
            <SkelLine width="220px" size="pill" />
          </div>
          <SkelLine width="65%" size="md" />
        </header>

        <Card padding="lg" className="analytics-panel analytics-funnel">
          <SkelPanelHead />
          <div className="analytics-skel-block analytics-skel-sankey" />
        </Card>

        <div className="analytics-kpis">
          {Array.from({ length: 8 }).map((_, i) => (
            <Card key={i} padding="md" className="analytics-kpi">
              <SkelLine width="60%" size="sm" />
              <SkelLine width="45%" size="xl" className="analytics-skel-gap" />
              <SkelLine width="85%" size="sm" />
            </Card>
          ))}
        </div>

        <div className="analytics-grid">
          {Array.from({ length: 2 }).map((_, i) => (
            <Card key={`row1-${i}`} padding="lg" className="analytics-panel">
              <SkelPanelHead />
              <div className="analytics-skel-block analytics-skel-panel-body" />
            </Card>
          ))}
        </div>
        <div className="analytics-grid">
          {Array.from({ length: 2 }).map((_, i) => (
            <Card key={`row2-${i}`} padding="lg" className="analytics-panel">
              <SkelPanelHead />
              <div className="analytics-skel-block analytics-skel-panel-body" />
            </Card>
          ))}
        </div>

        <Card padding="lg" className="analytics-panel">
          <SkelPanelHead />
          <div className="analytics-skel-rows">
            {Array.from({ length: 7 }).map((_, i) => (
              <SkelLine key={i} width="100%" size="row" />
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function Analytics() {
  const [days, setDays] = useState(30);
  const { data, error, loading } = useAnalytics(days);

  if (loading && !data) {
    return <AnalyticsSkeleton />;
  }
  if (!data) {
    return (
      <div className="analytics-page">
        <p className="analytics-empty">No se pudo leer el registro de llamadas. {error}</p>
      </div>
    );
  }

  const { coverage, latency, conversation, models, tools, funnel, langfuse, languages } = data;
  const llm = latency.llm_ms;

  return (
    <div className="analytics-page">
      <header className="home-hero">
        <p className="home-crumb">Clínica Arenal / Analytics</p>
        <div className="home-hero-row">
          <h1 className="home-title insights-title">Analytics</h1>
          <div className="home-toolbar" role="tablist" aria-label="Period">
            {RANGES.map((range) => (
              <button
                key={range.days}
                type="button"
                className={`home-chip ${days === range.days ? "on" : ""}`}
                onClick={() => setDays(range.days)}
              >
                {range.label}
              </button>
            ))}
          </div>
        </div>
        <p className="home-lead">
          Qué hace la línea con cada llamada, cuánto tarda y qué cuesta. {num(coverage.calls)}{" "}
          llamadas reales leídas del registro
          {coverage.excluded ? ` · ${num(coverage.excluded)} artefactos de evaluación excluidos` : ""}
          {error ? " · el feed va con retraso" : ""}.
        </p>
      </header>

      <Card padding="lg" className="analytics-panel analytics-funnel">
        <div className="analytics-panel-head">
          <div>
            <h2>Recorrido de la llamada</h2>
            <p>
              De {num(funnel.total)} llamadas a su desenlace. Pasa el ratón por una rama para
              seguirla.
            </p>
          </div>
        </div>
        <Sankey nodes={funnel.nodes} links={funnel.links} columns={funnel.columns} />
      </Card>

      <div className="analytics-kpis">
        {data.kpis.map((kpi) => (
          <Kpi key={kpi.key} label={kpi.label} value={kpi.value} caption={kpi.caption} />
        ))}
      </div>

      <div className="analytics-grid">
        <Card padding="lg" className="analytics-panel">
          <div className="analytics-panel-head">
            <div>
              <h2>Tiempo de respuesta</h2>
              <p>Del final del turno del paciente a la respuesta del agente.</p>
            </div>
          </div>
          <div className="analytics-stats">
            <Stat
              label="Registro · mediana"
              value={ms(latency.log_reply_ms.p50)}
              sub={`p90 ${ms(latency.log_reply_ms.p90)} · ${num(latency.log_reply_ms.n)} turnos`}
            />
            <Stat
              label="Micrófono · mediana"
              value={secs(latency.voice_reply_s.p50)}
              sub={
                latency.voice_reply_calls
                  ? `p90 ${secs(latency.voice_reply_s.p90)} · ${num(latency.voice_reply_calls)} llamadas de voz`
                  : "sin llamadas del carril de voz"
              }
            />
            <Stat
              label="Modelo · mediana"
              value={llm ? ms(llm.p50) : "—"}
              sub={
                llm
                  ? `p95 ${ms(llm.p90)} · ${num(llm.n)} respuestas · Langfuse`
                  : "Langfuse no conectado"
              }
            />
          </div>
          <Bars rows={latency.histogram} />
          <p className="analytics-note">
            La mediana del registro se mide sobre la línea escrita en el log, así que incluye
            nuestra propia escritura. La del micrófono la mide el detector de voz y sólo existe en
            el carril pipecat.
          </p>
        </Card>

        <Card padding="lg" className="analytics-panel">
          <div className="analytics-panel-head">
            <div>
              <h2>Quién lleva la conversación</h2>
              <p>Reparto de palabras entre el agente y el paciente.</p>
            </div>
          </div>
          <TalkSplit conversation={conversation} />
          <div className="analytics-stats">
            <Stat
              label="Turnos por llamada"
              value={conversation.turns.p50 ?? "—"}
              sub={`p90 ${conversation.turns.p90 ?? "—"}`}
            />
            <Stat
              label="Duración mediana"
              value={
                conversation.duration_s.p50 !== null
                  ? `${Math.round(conversation.duration_s.p50)} s`
                  : "—"
              }
              sub={
                conversation.duration_s.p90 !== null
                  ? `p90 ${Math.round(conversation.duration_s.p90)} s`
                  : "sin muestras"
              }
            />
            <Stat label="Llamadas con turnos" value={num(conversation.calls)} sub="de las leídas" />
          </div>
          <Bars rows={conversation.histogram} tone="ink" />
        </Card>
      </div>

      <div className="analytics-grid">
        <Card padding="lg" className="analytics-panel">
          <div className="analytics-panel-head">
            <div>
              <h2>Herramientas</h2>
              <p>
                Lo que la línea consulta en la API de la clínica.
                {langfuse ? " Las dos últimas columnas las mide Langfuse." : ""}
              </p>
            </div>
          </div>
          <div className="analytics-scroll">
            <table className="analytics-table">
              <thead>
                <tr>
                  <th>Herramienta</th>
                  <th className="num">Usos</th>
                  <th className="num">p50</th>
                  <th className="num">p90</th>
                  {langfuse ? <th className="num">LF p50</th> : null}
                  {langfuse ? <th className="num">LF p95</th> : null}
                  <th className="num">Fallos</th>
                </tr>
              </thead>
              <tbody>
                {tools.map((tool) => (
                  <tr key={tool.name}>
                    <td className="mono">{tool.name}</td>
                    <td className="num mono">{num(tool.calls)}</td>
                    <td className="num mono">{ms(tool.p50_ms)}</td>
                    <td className="num mono">{ms(tool.p90_ms)}</td>
                    {langfuse ? <td className="num mono">{ms(tool.langfuse_p50_ms)}</td> : null}
                    {langfuse ? <td className="num mono">{ms(tool.langfuse_p95_ms)}</td> : null}
                    <td className="num mono">
                      {tool.failures ? <em className="analytics-fail">{tool.failures}</em> : "0"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card padding="lg" className="analytics-panel">
          <div className="analytics-panel-head">
            <div>
              <h2>Modelos y coste</h2>
              <p>Sólo las {num(models.metered_calls)} llamadas que llevan contador.</p>
            </div>
          </div>
          <div className="analytics-stats">
            <Stat
              label="Coste del periodo"
              value={`${models.total_eur.toFixed(2).replace(".", ",")} €`}
              sub={
                models.eur_per_call
                  ? `${models.eur_per_call.toFixed(4).replace(".", ",")} € por llamada`
                  : "sin precio verificado"
              }
            />
            <Stat
              label="Tokens de entrada"
              value={num(models.tokens_in)}
              sub={`${num(models.tokens_out)} de salida`}
            />
            <Stat
              label="Audio transcrito"
              value={`${num(Math.round(models.stt_seconds / 60))} min`}
              sub={`${num(models.tts_characters)} caracteres hablados`}
            />
          </div>
          <dl className="analytics-models">
            {[
              ["LLM", models.llm],
              ["STT", models.stt],
              ["TTS", models.tts],
            ].map(([label, list]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>
                  {list.length
                    ? list.map((item) => (
                        <span key={item.name} className="analytics-model">
                          <code>{item.name}</code>
                          <em>{num(item.calls)}</em>
                        </span>
                      ))
                    : "—"}
                </dd>
              </div>
            ))}
            <div>
              <dt>Idiomas</dt>
              <dd>
                {languages.map((item) => (
                  <span key={item.code} className="analytics-model">
                    <code>{LANGUAGE_NAMES[item.code] || item.code}</code>
                    <em>{num(item.calls)}</em>
                  </span>
                ))}
              </dd>
            </div>
          </dl>
        </Card>
      </div>

      <Card padding="lg" className="analytics-panel">
        <div className="analytics-panel-head">
          <div>
            <h2>Llamadas</h2>
            <p>Las {num(data.calls.length)} más recientes del periodo, una fila por llamada.</p>
          </div>
        </div>
        <CallTable rows={data.calls} />
      </Card>

      <p className="analytics-foot">
        {num(coverage.calls)} llamadas · {num(coverage.with_turns)} con transcripción ·{" "}
        {num(coverage.with_log_reply)} con tiempo de respuesta · {num(coverage.with_voice_latency)}{" "}
        con telemetría de voz · {num(coverage.metered)} con contador de coste ·{" "}
        {langfuse
          ? `${num(langfuse.observations)} observaciones en Langfuse (${langfuse.environment})`
          : "Langfuse no conectado"}
        . Fuente: {SOURCE_LABEL[data.source?.kind] || data.source?.kind || "registro local"}.
      </p>
    </div>
  );
}
