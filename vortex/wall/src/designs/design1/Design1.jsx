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
import "./design1.css";

const CALL_CAP_SECONDS = 180;

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
    <div className="d1-duration">
      <div className="d1-duration-top">
        <span className="d1-eyebrow">Duración de la llamada</span>
        <span className="d1-duration-value">
          {formatClock(elapsed)} <span className="mute">/ {formatClock(CALL_CAP_SECONDS)}</span>
        </span>
      </div>
      <div className="d1-duration-track">
        <div className={`d1-duration-fill ${ratio > 0.8 ? "warn" : ""}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      <div className="d1-duration-chips">
        {call.language && <span className="d1-chip">{LANGUAGE_LABEL[call.language] || call.language}</span>}
        {call.idle_count > 0 && <span className="d1-chip warn">{call.idle_count}× silencio</span>}
      </div>
    </div>
  );
}

function Orb({ phase }) {
  const active = phase === "speaking" || phase === "working";
  const halo = useSpring({
    loop: active ? { reverse: true } : false,
    from: { scale: 0.9, opacity: 0.25 },
    to: { scale: active ? 1.35 : 1.06, opacity: active ? 0.55 : 0.2 },
    config: { duration: phase === "working" ? 700 : 1050 },
  });
  const core = useSpring({
    scale: active ? 1.04 : 1,
    config: { tension: 200, friction: 18 },
  });

  return (
    <div className="d1-orb-wrap">
      <animated.div className={`d1-orb-halo phase-${phase}`} style={halo} />
      <animated.div className={`d1-orb-core phase-${phase}`} style={core}>
        <span className="d1-orb-ring" />
        <PhaseIcon phase={phase} size={30} className="d1-orb-icon" />
      </animated.div>
      <div className="d1-orb-label">{PHASE_LABEL[phase] || phase}</div>
    </div>
  );
}

const PHASE_LABEL = {
  connecting: "Conectando",
  thinking: "Pensando",
  speaking: "Hablando",
  working: "Ejecutando herramienta",
  listening: "Escuchando",
  ended: "Finalizada",
};

function ToolSquare({ items }) {
  const focus = deriveToolFocus(items);

  return (
    <div className="d1-tool-card">
      <div className="d1-tool-card-head">
        <span className="d1-eyebrow">
          {focus.mode === "recent" ? "Últimas herramientas" : "Demo en directo"}
        </span>
      </div>
      <div className="d1-tool-card-body">
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
    from: { opacity: 0, transform: "translateY(22px)" },
    enter: { opacity: 1, transform: "translateY(0px)" },
    update: { opacity: 1, transform: "translateY(0px)" },
    config: { tension: 300, friction: 30 },
  });

  return (
    <div className="d1-chat">
      <header className="d1-chat-head">
        <span className="d1-dot-live" />
        <span className="d1-chat-title">
          Transcripción <em>en vivo</em>
        </span>
      </header>
      <div className="d1-chat-stream">
        {items.length === 0 && <p className="d1-empty">Esperando a que empiece la llamada…</p>}
        {transitions((style, item) => {
          const isUser = item.role === "user";
          return (
            <animated.div style={style} className={`d1-row ${isUser ? "user" : "assistant"}`}>
              <div className={`d1-bubble ${isUser ? "user" : "assistant"}`}>
                <span className="d1-who">{isUser ? "Paciente" : "Agente Vortex"}</span>
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
    <div className="d1-insight-card">
      <span className="d1-insight-title">{card.title}</span>
      <span className="d1-insight-value">{card.value}</span>
      {card.rule && <span className="d1-insight-rule">{card.rule}</span>}
    </div>
  );
}

function FinalAction({ call }) {
  const final = deriveFinalAction(call);
  const ratio = final.showCountdown ? Math.max(0, final.submitRemaining) / (call?.submit_window_secs ?? 30) : 1;

  const pop = useSpring({
    opacity: call ? 1 : 0.5,
    transform: call && !call.live ? "scale(1)" : "scale(0.98)",
    config: { tension: 220, friction: 22 },
  });

  return (
    <animated.div style={pop} className={`d1-final ${final.accepted ? "done" : ""}`}>
      <div className="d1-final-top">
        <div>
          <span className="d1-eyebrow on-dark">Acción final</span>
          <span className="d1-final-value">{final.label}</span>
        </div>
        {final.showCountdown && (
          <CountdownRing ratio={ratio} size={46} stroke={3.5} className="d1-ring">
            <span className="d1-ring-text">{Math.max(0, Math.round(final.submitRemaining))}s</span>
          </CountdownRing>
        )}
      </div>
      {call?.decline_reason && <span className="d1-final-note">Motivo: {call.decline_reason}</span>}
      {final.duplicateBlocked && <span className="d1-final-note warn">Envío duplicado bloqueado</span>}
    </animated.div>
  );
}

export default function Design1({ items, turnItems, intent, call, phase }) {
  const cards = buildInsightCards(items, intent);
  const cardTransitions = useTransition(cards, {
    keys: (c) => c.id,
    from: { opacity: 0, transform: "translateX(18px)" },
    enter: { opacity: 1, transform: "translateX(0px)" },
    update: { opacity: 1, transform: "translateX(0px)" },
    config: { tension: 260, friction: 26 },
  });

  return (
    <div className="design1-root">
      <div className="d1-ambient" aria-hidden="true" />
      <div className="d1-shell">
        <aside className="d1-left">
          <Duration call={call} />
          <Orb phase={phase} />
          <ToolSquare items={items} />
        </aside>

        <main className="d1-main">
          <Chat items={turnItems} />
        </main>

        <aside className="d1-right">
          <div className="d1-insight-list">
            {cards.length === 0 && <p className="d1-empty">Sin información extraída todavía.</p>}
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
