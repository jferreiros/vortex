import { useEffect, useState } from "react";
import { useSpring, useTransition, animated } from "@react-spring/web";
import { formatClock } from "../../lib/dates";
import { LANGUAGE_LABEL } from "../../lib/labels";
import { PhaseIcon, ToolIcon } from "../../lib/icons";
import { buildInsightCards, deriveFinalAction, deriveToolFocus } from "../../lib/derive";
import CountdownRing from "../../components/CountdownRing";
import Stage from "../../components/Stage";
import ToolLiveView from "../../components/ToolLiveView";
import RecentToolsList from "../../components/RecentToolsList";
import "./design7.css";

const CALL_CAP_SECONDS = 180;
const PHASE_LABEL = {
  connecting: "Conectando",
  thinking: "Pensando",
  speaking: "Hablando",
  working: "Ejecutando herramienta",
  listening: "Escuchando",
  ended: "Finalizada",
};

function Duration({ call }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  if (!call) return null;

  const startedMs = call.started_at ? new Date(call.started_at).getTime() : null;
  const elapsed = call.live
    ? startedMs
      ? (Date.now() - startedMs) / 1000
      : 0
    : call.duration_ms != null
      ? call.duration_ms / 1000
      : 0;
  const ratio = Math.min(1, elapsed / CALL_CAP_SECONDS);

  return (
    <div className="d7-duration">
      <span className="d7-label">Duración</span>
      <div className="d7-duration-row">
        <div className="d7-duration-track">
          <div className="d7-duration-fill" style={{ width: `${ratio * 100}%` }} />
        </div>
        <span className="d7-duration-value mono">
          {formatClock(elapsed)}/{formatClock(CALL_CAP_SECONDS)}
        </span>
      </div>
      <div className="d7-meta-row">
        {call.language && <span>{LANGUAGE_LABEL[call.language] || call.language}</span>}
        {call.idle_count > 0 && <span className="warn">{call.idle_count}× silencio</span>}
      </div>
    </div>
  );
}

function Orb({ phase }) {
  return (
    <div className="d7-orb-wrap">
      <div className={`d7-orb phase-${phase}`}>
        <PhaseIcon phase={phase} size={26} />
      </div>
      <div className="d7-orb-label">{PHASE_LABEL[phase] || phase}</div>
    </div>
  );
}

function ToolSquare({ items }) {
  const focus = deriveToolFocus(items);
  return (
    <div className="d7-tool-card">
      <span className="d7-label">{focus.mode === "recent" ? "Últimas herramientas" : "Demo en directo"}</span>
      <div className="d7-tool-card-body">
        {focus.mode === "stage" && <Stage tool={focus.tool} IconComponent={ToolIcon} />}
        {focus.mode === "live" && <ToolLiveView tool={focus.tool} IconComponent={ToolIcon} />}
        {focus.mode === "recent" && <RecentToolsList items={focus.recent} IconComponent={ToolIcon} />}
      </div>
    </div>
  );
}

function Chat({ items }) {
  const transitions = useTransition(items, {
    keys: (item) => item.id,
    from: { opacity: 0 },
    enter: { opacity: 1 },
    update: { opacity: 1 },
    config: { tension: 300, friction: 30 },
  });

  return (
    <div className="d7-chat">
      <header className="d7-chat-head">
        <span className="d7-dot-live" />
        Transcripción
      </header>
      <div className="d7-chat-stream">
        {items.length === 0 && <p className="d7-empty">Esperando a que empiece la llamada.</p>}
        {transitions((style, item, _t, index) => {
          const isUser = item.role === "user";
          return (
            <animated.div style={style} className={`d7-row ${isUser ? "user" : "assistant"}`}>
              <span className="d7-idx mono">{String(index + 1).padStart(2, "0")}</span>
              <div className="d7-row-body">
                <span className="d7-who">{isUser ? "Paciente" : "Agente Vortex"}</span>
                <p>{item.text}</p>
              </div>
            </animated.div>
          );
        })}
      </div>
    </div>
  );
}

function InsightCard({ card }) {
  return (
    <div className="d7-insight-row">
      <span className="d7-insight-title">{card.title}</span>
      <span className="d7-insight-value">{card.value}</span>
      {card.rule && <span className="d7-insight-rule">{card.rule}</span>}
    </div>
  );
}

function FinalAction({ call }) {
  const final = deriveFinalAction(call);
  const ratio = final.showCountdown ? Math.max(0, final.submitRemaining) / (call?.submit_window_secs ?? 30) : 1;
  const pop = useSpring({
    opacity: call ? 1 : 0.5,
    config: { tension: 240, friction: 24 },
  });

  return (
    <animated.div style={pop} className={`d7-final ${final.accepted ? "done" : ""}`}>
      <div className="d7-final-top">
        <div>
          <span className="d7-label on-dark">Acción final</span>
          <span className="d7-final-value">{final.label}</span>
        </div>
        {final.showCountdown && (
          <CountdownRing ratio={ratio} size={40} stroke={2} className="d7-ring">
            <span className="mono">{Math.max(0, Math.round(final.submitRemaining))}</span>
          </CountdownRing>
        )}
      </div>
      {call?.decline_reason && <span className="d7-final-note">Motivo: {call.decline_reason}</span>}
      {final.duplicateBlocked && <span className="d7-final-note warn">Envío duplicado bloqueado</span>}
    </animated.div>
  );
}

export default function Design7({ items, turnItems, intent, call, phase }) {
  const cards = buildInsightCards(items, intent);
  const cardTransitions = useTransition(cards, {
    keys: (c) => c.id,
    from: { opacity: 0 },
    enter: { opacity: 1 },
    update: { opacity: 1 },
    config: { tension: 260, friction: 28 },
  });

  return (
    <div className="design7-root">
      <div className="d7-shell">
        <aside className="d7-left">
          <Duration call={call} />
          <Orb phase={phase} />
          <ToolSquare items={items} />
        </aside>

        <main className="d7-main">
          <Chat items={turnItems} />
        </main>

        <aside className="d7-right">
          <span className="d7-label">Datos extraídos</span>
          <div className="d7-insight-list">
            {cards.length === 0 && <p className="d7-empty">Sin información todavía.</p>}
            {cardTransitions((style, card) => (
              <animated.div style={style}>
                <InsightCard card={card} />
              </animated.div>
            ))}
          </div>
          <FinalAction call={call} />
        </aside>
      </div>
    </div>
  );
}
