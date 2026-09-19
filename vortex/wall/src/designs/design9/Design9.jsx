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
import "./design9.css";

const CALL_CAP_SECONDS = 180;
const PHASE_LABEL = {
  connecting: "Conectando",
  thinking: "Pensando",
  speaking: "Hablando",
  working: "Un momento…",
  listening: "Escuchando",
  ended: "¡Listo!",
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
    <div className="d9-duration">
      <div className="d9-duration-head">
        <span className="d9-kicker">Duración</span>
        <span className="d9-duration-value">
          {formatClock(elapsed)} <span>/ {formatClock(CALL_CAP_SECONDS)}</span>
        </span>
      </div>
      <div className="d9-duration-track">
        <div className={`d9-duration-fill ${ratio > 0.8 ? "warn" : ""}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      <div className="d9-duration-chips">
        {call.language && <span className="d9-chip">{LANGUAGE_LABEL[call.language] || call.language}</span>}
        {call.idle_count > 0 && <span className="d9-chip warn">{call.idle_count}× silencio</span>}
      </div>
    </div>
  );
}

function Orb({ phase }) {
  const active = phase === "speaking" || phase === "working";
  const bounce = useSpring({
    loop: active ? { reverse: true } : false,
    from: { scale: 0.96 },
    to: { scale: active ? 1.07 : 1 },
    config: { tension: 260, friction: 12 },
  });

  return (
    <div className="d9-orb-wrap">
      <animated.div className={`d9-orb phase-${phase}`} style={bounce}>
        <PhaseIcon phase={phase} size={32} />
      </animated.div>
      <div className="d9-orb-label">{PHASE_LABEL[phase] || phase}</div>
    </div>
  );
}

function ToolSquare({ items }) {
  const focus = deriveToolFocus(items);
  return (
    <div className="d9-tool-card">
      <span className="d9-kicker">{focus.mode === "recent" ? "Últimas herramientas" : "Demo en directo"}</span>
      <div className="d9-tool-card-body">
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
    from: { opacity: 0, transform: "translateY(20px) scale(0.94)" },
    enter: { opacity: 1, transform: "translateY(0px) scale(1)" },
    update: { opacity: 1, transform: "translateY(0px) scale(1)" },
    config: { tension: 300, friction: 22 },
  });

  return (
    <div className="d9-chat">
      <header className="d9-chat-head">
        <span className="d9-dot-live" />
        Transcripción
      </header>
      <div className="d9-chat-stream">
        {items.length === 0 && <p className="d9-empty">Esperando a que empiece la llamada…</p>}
        {transitions((style, item) => {
          const isUser = item.role === "user";
          return (
            <animated.div style={style} className={`d9-row ${isUser ? "user" : "assistant"}`}>
              <div className={`d9-bubble ${isUser ? "user" : "assistant"}`}>
                <span className="d9-who">{isUser ? "Paciente" : "Agente"}</span>
                <p>{item.text}</p>
              </div>
            </animated.div>
          );
        })}
      </div>
    </div>
  );
}

const TONES = ["mint", "lavender", "peach", "sky"];

function InsightCard({ card, idx }) {
  return (
    <div className={`d9-insight-card tone-${TONES[idx % TONES.length]}`}>
      <span className="d9-insight-title">{card.title}</span>
      <span className="d9-insight-value">{card.value}</span>
      {card.rule && <span className="d9-insight-rule">{card.rule}</span>}
    </div>
  );
}

function FinalAction({ call }) {
  const final = deriveFinalAction(call);
  const ratio = final.showCountdown ? Math.max(0, final.submitRemaining) / (call?.submit_window_secs ?? 30) : 1;
  const pop = useSpring({
    opacity: call ? 1 : 0.55,
    transform: call && !call.live ? "scale(1)" : "scale(0.98)",
    config: { tension: 260, friction: 20 },
  });

  return (
    <animated.div style={pop} className={`d9-final ${final.accepted ? "done" : ""}`}>
      <div className="d9-final-top">
        <div>
          <span className="d9-kicker on-dark">Acción final</span>
          <span className="d9-final-value">{final.label}</span>
        </div>
        {final.showCountdown && (
          <CountdownRing ratio={ratio} size={46} stroke={4} className="d9-ring">
            <span>{Math.max(0, Math.round(final.submitRemaining))}s</span>
          </CountdownRing>
        )}
      </div>
      {call?.decline_reason && <span className="d9-final-note">Motivo: {call.decline_reason}</span>}
      {final.duplicateBlocked && <span className="d9-final-note warn">Envío duplicado bloqueado</span>}
    </animated.div>
  );
}

export default function Design9({ items, turnItems, intent, call, phase }) {
  const cards = buildInsightCards(items, intent);
  const cardTransitions = useTransition(cards, {
    keys: (c) => c.id,
    from: { opacity: 0, transform: "translateX(18px) scale(0.94)" },
    enter: { opacity: 1, transform: "translateX(0px) scale(1)" },
    update: { opacity: 1, transform: "translateX(0px) scale(1)" },
    config: { tension: 260, friction: 24 },
  });

  return (
    <div className="design9-root">
      <div className="d9-shell">
        <aside className="d9-left">
          <Duration call={call} />
          <Orb phase={phase} />
          <ToolSquare items={items} />
        </aside>

        <main className="d9-main">
          <Chat items={turnItems} />
        </main>

        <aside className="d9-right">
          <div className="d9-insight-list">
            {cards.length === 0 && <p className="d9-empty">Todavía no hay información.</p>}
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
