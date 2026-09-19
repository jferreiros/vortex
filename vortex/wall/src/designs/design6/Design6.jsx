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
import "./design6.css";

const CALL_CAP_SECONDS = 180;
const PHASE_LABEL = {
  connecting: "CONECTANDO",
  thinking: "PENSANDO",
  speaking: "HABLANDO",
  working: "EJECUTANDO",
  listening: "ESCUCHANDO",
  ended: "TERMINADA",
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
    <div className="d6-duration">
      <div className="d6-duration-head">
        <span className="d6-label">DURACIÓN</span>
        <span className="d6-duration-value">
          {formatClock(elapsed)}<span className="mute">/{formatClock(CALL_CAP_SECONDS)}</span>
        </span>
      </div>
      <div className="d6-duration-track">
        <div className={`d6-duration-fill ${ratio > 0.8 ? "warn" : ""}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      <div className="d6-duration-chips">
        {call.language && <span className="d6-chip">{(LANGUAGE_LABEL[call.language] || call.language).toUpperCase()}</span>}
        {call.idle_count > 0 && <span className="d6-chip warn">{call.idle_count}× SILENCIO</span>}
      </div>
    </div>
  );
}

function Orb({ phase }) {
  const active = phase === "speaking" || phase === "working";
  const thump = useSpring({
    loop: active ? { reverse: true } : false,
    from: { transform: "scale(1) rotate(-2deg)" },
    to: { transform: active ? "scale(1.12) rotate(2deg)" : "scale(1) rotate(-2deg)" },
    config: { tension: 340, friction: 12 },
  });

  return (
    <div className="d6-orb-wrap">
      <animated.div className={`d6-orb phase-${phase}`} style={thump}>
        <PhaseIcon phase={phase} size={34} />
      </animated.div>
      <div className="d6-orb-label">{PHASE_LABEL[phase] || phase.toUpperCase()}</div>
    </div>
  );
}

function ToolSquare({ items }) {
  const focus = deriveToolFocus(items);
  return (
    <div className="d6-tool-card">
      <div className="d6-tool-card-head">
        {focus.mode === "recent" ? "ÚLTIMAS HERRAMIENTAS" : "DEMO EN DIRECTO"}
      </div>
      <div className="d6-tool-card-body">
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
    from: { opacity: 0, transform: "translateY(18px)" },
    enter: { opacity: 1, transform: "translateY(0px)" },
    update: { opacity: 1, transform: "translateY(0px)" },
    config: { tension: 340, friction: 24 },
  });

  return (
    <div className="d6-chat">
      <header className="d6-chat-head">
        <span className="d6-dot-live" />
        TRANSCRIPCIÓN
      </header>
      <div className="d6-chat-stream">
        {items.length === 0 && <p className="d6-empty">ESPERANDO LLAMADA…</p>}
        {transitions((style, item) => {
          const isUser = item.role === "user";
          return (
            <animated.div style={style} className={`d6-row ${isUser ? "user" : "assistant"}`}>
              <div className={`d6-bubble ${isUser ? "user" : "assistant"}`}>
                <span className="d6-who">{isUser ? "PACIENTE" : "AGENTE"}</span>
                <p>{item.text}</p>
              </div>
            </animated.div>
          );
        })}
      </div>
    </div>
  );
}

function InsightCard({ card, idx }) {
  return (
    <div className={`d6-insight-card tone-${idx % 2}`}>
      <span className="d6-insight-title">{card.title.toUpperCase()}</span>
      <span className="d6-insight-value">{card.value}</span>
      {card.rule && <span className="d6-insight-rule">{card.rule}</span>}
    </div>
  );
}

function FinalAction({ call }) {
  const final = deriveFinalAction(call);
  const ratio = final.showCountdown ? Math.max(0, final.submitRemaining) / (call?.submit_window_secs ?? 30) : 1;
  const pop = useSpring({
    opacity: call ? 1 : 0.6,
    transform: call && !call.live ? "scale(1)" : "scale(0.98)",
    config: { tension: 300, friction: 18 },
  });

  return (
    <animated.div style={pop} className={`d6-final ${final.accepted ? "done" : ""}`}>
      <div className="d6-final-top">
        <div>
          <span className="d6-label on-dark">ACCIÓN FINAL</span>
          <span className="d6-final-value">{final.label.toUpperCase()}</span>
        </div>
        {final.showCountdown && (
          <CountdownRing ratio={ratio} size={46} stroke={4} className="d6-ring">
            <span className="d6-ring-text">{Math.max(0, Math.round(final.submitRemaining))}s</span>
          </CountdownRing>
        )}
      </div>
      {call?.decline_reason && <span className="d6-final-note">MOTIVO: {call.decline_reason.toUpperCase()}</span>}
      {final.duplicateBlocked && <span className="d6-final-note warn">ENVÍO DUPLICADO BLOQUEADO</span>}
    </animated.div>
  );
}

export default function Design6({ items, turnItems, intent, call, phase }) {
  const cards = buildInsightCards(items, intent);
  const cardTransitions = useTransition(cards, {
    keys: (c) => c.id,
    from: { opacity: 0, transform: "translateX(14px)" },
    enter: { opacity: 1, transform: "translateX(0px)" },
    update: { opacity: 1, transform: "translateX(0px)" },
    config: { tension: 320, friction: 22 },
  });

  return (
    <div className="design6-root">
      <div className="d6-shell">
        <aside className="d6-left">
          <Duration call={call} />
          <Orb phase={phase} />
          <ToolSquare items={items} />
        </aside>

        <main className="d6-main">
          <Chat items={turnItems} />
        </main>

        <aside className="d6-right">
          <div className="d6-insight-list">
            {cards.length === 0 && <p className="d6-empty">SIN DATOS TODAVÍA.</p>}
            {cardTransitions((style, card) => {
              const idx = cards.findIndex((c) => c.id === card.id);
              return (
                <animated.div style={style}>
                  <InsightCard card={card} idx={idx} />
                </animated.div>
              );
            })}
          </div>
          <FinalAction call={call} />
        </aside>
      </div>
    </div>
  );
}
