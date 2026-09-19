import { useEffect, useRef, useState } from "react";
import { useSpring, useTransition, animated } from "@react-spring/web";
import { toolMeta } from "../../lib/tools";
import { formatClock } from "../../lib/dates";
import { LANGUAGE_LABEL, INTENT_LABEL } from "../../lib/labels";
import { buildInsightCards, deriveFinalAction } from "../../lib/derive";
import CountdownRing from "../../components/CountdownRing";
import "./design5.css";

const CALL_CAP_SECONDS = 180;

function formatStamp(ts) {
  if (!ts) return "--:--:--";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "--:--:--";
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  const s = String(d.getSeconds()).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

// The headline only promotes a name once the match is unambiguous — a
// single result, or find_patient/build_registration's own single-record
// shape. Two candidates still waiting on the caller stays generic.
function derivePatientName(items) {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const item = items[i];
    if (item.type !== "tool" || item.status === "running") continue;
    if (!["find_patient", "build_registration"].includes(item.tool)) continue;
    const result = item.result || {};
    const record = result.patient || (Array.isArray(result.candidates) && result.candidates.length === 1 ? result.candidates[0] : null);
    if (record?.full_name) return record.full_name;
  }
  return null;
}

function Masthead({ call, phase }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const startedMs = call?.started_at ? new Date(call.started_at).getTime() : null;
  const elapsed = call
    ? call.live
      ? startedMs
        ? (Date.now() - startedMs) / 1000
        : 0
      : (call.duration_ms ?? 0) / 1000
    : 0;

  return (
    <header className="d5-masthead">
      <div className="d5-masthead-brand">
        <span className="d5-live-dot" />
        VORTEX — REGISTRO EN VIVO
      </div>
      <div className="d5-masthead-meta">
        <span>Clínica Arenal</span>
        <span>·</span>
        <span>{phase === "ended" ? "Cerrada" : "Edición en curso"}</span>
        <span>·</span>
        <span className="mono">
          {formatClock(elapsed)} / {formatClock(CALL_CAP_SECONDS)}
        </span>
        {call?.language && (
          <>
            <span>·</span>
            <span>{LANGUAGE_LABEL[call.language] || call.language}</span>
          </>
        )}
      </div>
    </header>
  );
}

function Headline({ items, intent, call }) {
  const final = deriveFinalAction(call);
  const ended = call && !call.live;
  const patientName = derivePatientName(items);

  let headline = "Nueva llamada entrante";
  let kicker = "Esperando datos del paciente";
  if (ended) {
    headline = final.label;
    kicker = call?.decline_reason ? `Motivo: ${call.decline_reason}` : "Resultado de la llamada";
  } else if (patientName) {
    headline = patientName;
    kicker = intent ? INTENT_LABEL[intent] || intent : "Llamada en curso";
  } else if (intent) {
    headline = INTENT_LABEL[intent] || intent;
    kicker = "Llamada en curso";
  }

  const spring = useSpring({
    key: headline,
    from: { opacity: 0, transform: "translateY(10px)" },
    to: { opacity: 1, transform: "translateY(0px)" },
    config: { tension: 210, friction: 24 },
  });

  return (
    <div className="d5-headline-block">
      <span className={`d5-kicker ${ended ? "ended" : ""}`}>{kicker}</span>
      <animated.h1 style={spring} className="d5-headline">
        {headline}
      </animated.h1>
    </div>
  );
}

function StreamEntry({ item }) {
  if (item.type === "turn") {
    const isUser = item.role === "user";
    return (
      <div className={`d5-entry turn ${isUser ? "user" : "assistant"}`}>
        <span className="d5-stamp mono">{formatStamp(item.ts)}</span>
        <div className="d5-entry-body">
          <span className="d5-entry-who">{isUser ? "Paciente" : "Agente Vortex"}</span>
          <p className={isUser ? "d5-quote" : "d5-plain"}>{item.text}</p>
        </div>
      </div>
    );
  }

  const meta = toolMeta(item.tool);
  const failed = item.status === "fail";
  return (
    <div className={`d5-entry tool ${failed ? "fail" : ""}`}>
      <span className="d5-stamp mono">{formatStamp(item.ts)}</span>
      <div className="d5-entry-body">
        <p className="d5-note">
          <em>Nota de redacción —</em> {meta.label.toLowerCase()}
          {item.status === "running" ? ", en curso…" : failed ? ", con error." : `, resuelto en ${Math.round(item.ms ?? 0)} ms.`}
        </p>
      </div>
    </div>
  );
}

function Marginalia({ items, intent, call }) {
  const cards = buildInsightCards(items, intent);
  const final = deriveFinalAction(call);
  const ratio = final.showCountdown ? Math.max(0, final.submitRemaining) / (call?.submit_window_secs ?? 30) : 1;
  const transitions = useTransition(cards, {
    keys: (c) => c.id,
    from: { opacity: 0, transform: "translateY(8px)" },
    enter: { opacity: 1, transform: "translateY(0px)" },
    config: { tension: 230, friction: 26 },
  });

  return (
    <div className="d5-margin-inner">
      <span className="d5-margin-kicker">Al margen</span>
      {cards.length === 0 && <p className="d5-margin-empty">Sin datos extraídos todavía.</p>}
      {transitions((style, card) => (
        <animated.div style={style} className="d5-margin-note">
          <span className="d5-margin-title">{card.title}</span>
          <span className="d5-margin-value">{card.value}</span>
          {card.rule && <span className="d5-margin-rule">{card.rule}</span>}
        </animated.div>
      ))}

      <div className={`d5-verdict-box ${final.accepted ? "done" : ""}`}>
        <span className="d5-margin-kicker on-dark">Acción final</span>
        <span className="d5-verdict-value">{final.label}</span>
        {final.showCountdown && (
          <div className="d5-verdict-countdown">
            <CountdownRing ratio={ratio} size={30} stroke={2.5} className="d5-ring" />
            <span className="mono">{Math.max(0, Math.round(final.submitRemaining))}s restantes</span>
          </div>
        )}
        {final.duplicateBlocked && <span className="d5-verdict-note">Envío duplicado bloqueado</span>}
      </div>
    </div>
  );
}

export default function Design5({ items, intent, call, phase }) {
  const streamRef = useRef(null);
  useEffect(() => {
    if (streamRef.current) streamRef.current.scrollTop = streamRef.current.scrollHeight;
  }, [items.length]);

  return (
    <div className="design5-root">
      <Masthead call={call} phase={phase} />
      <div className="d5-page">
        <Headline items={items} intent={intent} call={call} />

        <div className="d5-layout">
          <main className="d5-stream" ref={streamRef}>
            {items.length === 0 && <p className="d5-stream-empty">La edición en vivo empieza en cuanto suena el teléfono.</p>}
            {items.map((item) => (
              <StreamEntry key={item.id} item={item} />
            ))}
          </main>

          <aside className="d5-margin">
            <Marginalia items={items} intent={intent} call={call} />
          </aside>
        </div>
      </div>
    </div>
  );
}
