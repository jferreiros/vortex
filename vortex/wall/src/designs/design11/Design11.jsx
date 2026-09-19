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
import "./design11.css";

const CALL_CAP_SECONDS = 180;
const PHASE_LABEL = {
  connecting: "Conectando",
  thinking: "Analizando",
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
    <div className="d11-duration">
      <div className="d11-duration-head">
        <span className="d11-label">Duración</span>
        <span className="d11-duration-value">
          {formatClock(elapsed)} <span>/ {formatClock(CALL_CAP_SECONDS)}</span>
        </span>
      </div>
      <div className="d11-duration-track">
        <div className={`d11-duration-fill ${ratio > 0.8 ? "warn" : ""}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      {(call.language || call.idle_count > 0) && (
        <div className="d11-duration-chips">
          {call.language && <span className="d11-chip">{LANGUAGE_LABEL[call.language] || call.language}</span>}
          {call.idle_count > 0 && <span className="d11-chip warn">{call.idle_count}× silencio</span>}
        </div>
      )}
    </div>
  );
}

function Orb({ phase }) {
  const active = phase === "speaking" || phase === "working";
  const pulse = useSpring({
    loop: active ? { reverse: true } : false,
    from: { scale: 0.97, opacity: 0.3 },
    to: { scale: active ? 1.14 : 1.03, opacity: active ? 0.55 : 0.22 },
    config: { duration: phase === "working" ? 780 : 1250 },
  });

  return (
    <div className="d11-orb-wrap">
      <animated.span className={`d11-orb-halo phase-${phase}`} style={pulse} />
      <div className={`d11-orb phase-${phase}`}>
        <PhaseIcon phase={phase} size={26} />
      </div>
      <div className="d11-orb-label">{PHASE_LABEL[phase] || phase}</div>
    </div>
  );
}

function ToolSquare({ items }) {
  const focus = deriveToolFocus(items);
  return (
    <div className="d11-tool-card">
      <span className="d11-label">{focus.mode === "recent" ? "Últimas herramientas" : "Demo en directo"}</span>
      <div className="d11-tool-card-body">
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
    from: { opacity: 0, transform: "translateY(14px)" },
    enter: { opacity: 1, transform: "translateY(0px)" },
    update: { opacity: 1, transform: "translateY(0px)" },
    config: { tension: 290, friction: 30 },
  });

  return (
    <div className="d11-chat">
      <header className="d11-chat-head">
        <span className="d11-dot-live" />
        Transcripción
      </header>
      <div className="d11-chat-stream">
        {items.length === 0 && <p className="d11-empty">Esperando a que empiece la llamada…</p>}
        {transitions((style, item) => {
          const isUser = item.role === "user";
          return (
            <animated.div style={style} className={`d11-row ${isUser ? "user" : "assistant"}`}>
              <div className={`d11-bubble ${isUser ? "user" : "assistant"}`}>
                <span className="d11-who">{isUser ? "Paciente" : "Agente Vortex"}</span>
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
    <div className="d11-insight-card">
      <span className="d11-insight-title">{card.title}</span>
      <span className="d11-insight-value">{card.value}</span>
      {card.rule && <span className="d11-insight-rule">{card.rule}</span>}
    </div>
  );
}

function FinalAction({ call }) {
  const final = deriveFinalAction(call);
  const ratio = final.showCountdown ? Math.max(0, final.submitRemaining) / (call?.submit_window_secs ?? 30) : 1;
  const pop = useSpring({
    opacity: call ? 1 : 0.55,
    transform: call && !call.live ? "scale(1)" : "scale(0.99)",
    config: { tension: 240, friction: 24 },
  });

  return (
    <animated.div style={pop} className={`d11-final ${final.accepted ? "done" : ""}`}>
      <div className="d11-final-top">
        <div>
          <span className="d11-label on-dark">Acción final</span>
          <span className="d11-final-value">{final.label}</span>
        </div>
        {final.showCountdown && (
          <CountdownRing ratio={ratio} size={42} stroke={3} className="d11-ring">
            <span className="mono">{Math.max(0, Math.round(final.submitRemaining))}s</span>
          </CountdownRing>
        )}
      </div>
      {call?.decline_reason && <span className="d11-final-note">Motivo: {call.decline_reason}</span>}
      {final.duplicateBlocked && <span className="d11-final-note warn">Envío duplicado bloqueado</span>}
    </animated.div>
  );
}

export default function Design11({ items, turnItems, intent, call, phase }) {
  const cards = buildInsightCards(items, intent);
  const cardTransitions = useTransition(cards, {
    keys: (c) => c.id,
    from: { opacity: 0, transform: "translateY(8px)" },
    enter: { opacity: 1, transform: "translateY(0px)" },
    update: { opacity: 1, transform: "translateY(0px)" },
    config: { tension: 260, friction: 28 },
  });

  return (
    <div className="design11-root">
      <div className="d11-shell">
        <aside className="d11-left">
          <Duration call={call} />
          <Orb phase={phase} />
          <ToolSquare items={items} />
        </aside>

        <main className="d11-main">
          <Chat items={turnItems} />
        </main>

        <aside className="d11-right">
          <span className="d11-label">Datos extraídos</span>
          <div className="d11-insight-list">
            {cards.length === 0 && <p className="d11-empty">Sin información todavía.</p>}
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
