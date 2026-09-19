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
import "./design8.css";

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
    <div className="d8-duration">
      <div className="d8-duration-head">
        <span className="d8-kicker">Duración</span>
        <span className="d8-duration-value">
          {formatClock(elapsed)} <span>/ {formatClock(CALL_CAP_SECONDS)}</span>
        </span>
      </div>
      <div className="d8-duration-track">
        <div className="d8-duration-fill" style={{ width: `${ratio * 100}%` }} />
      </div>
      <div className="d8-duration-chips">
        {call.language && <span className="d8-chip">{LANGUAGE_LABEL[call.language] || call.language}</span>}
        {call.idle_count > 0 && <span className="d8-chip warn">{call.idle_count}× silencio</span>}
      </div>
    </div>
  );
}

function Orb({ phase }) {
  const active = phase === "speaking" || phase === "working";
  const glow = useSpring({
    loop: active ? { reverse: true } : false,
    from: { opacity: 0.4, scale: 0.96 },
    to: { opacity: active ? 0.9 : 0.5, scale: active ? 1.08 : 1 },
    config: { duration: 1200 },
  });

  return (
    <div className="d8-orb-wrap">
      <animated.span className="d8-orb-halo" style={glow} />
      <div className="d8-orb">
        <span className="d8-orb-ring" />
        <PhaseIcon phase={phase} size={28} />
      </div>
      <div className="d8-orb-label">{PHASE_LABEL[phase] || phase}</div>
    </div>
  );
}

function ToolSquare({ items }) {
  const focus = deriveToolFocus(items);
  return (
    <div className="d8-tool-card">
      <span className="d8-kicker">{focus.mode === "recent" ? "Últimas herramientas" : "Demo en directo"}</span>
      <div className="d8-tool-card-body">
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
    config: { tension: 260, friction: 30 },
  });

  return (
    <div className="d8-chat">
      <header className="d8-chat-head">
        <span className="d8-dot-live" />
        <span className="d8-chat-title">Transcripción</span>
      </header>
      <div className="d8-chat-stream">
        {items.length === 0 && <p className="d8-empty">Esperando a que empiece la llamada…</p>}
        {transitions((style, item) => {
          const isUser = item.role === "user";
          return (
            <animated.div style={style} className={`d8-row ${isUser ? "user" : "assistant"}`}>
              <div className={`d8-bubble ${isUser ? "user" : "assistant"}`}>
                <span className="d8-who">{isUser ? "Paciente" : "Agente Vortex"}</span>
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
    <div className="d8-insight-card">
      <span className="d8-insight-title">{card.title}</span>
      <span className="d8-insight-value">{card.value}</span>
      {card.rule && <span className="d8-insight-rule">{card.rule}</span>}
    </div>
  );
}

function FinalAction({ call }) {
  const final = deriveFinalAction(call);
  const ratio = final.showCountdown ? Math.max(0, final.submitRemaining) / (call?.submit_window_secs ?? 30) : 1;
  const pop = useSpring({
    opacity: call ? 1 : 0.5,
    config: { tension: 220, friction: 24 },
  });

  return (
    <animated.div style={pop} className={`d8-final ${final.accepted ? "done" : ""}`}>
      <div className="d8-final-top">
        <div>
          <span className="d8-kicker">Acción final</span>
          <span className="d8-final-value">{final.label}</span>
        </div>
        {final.showCountdown && (
          <CountdownRing ratio={ratio} size={44} stroke={2.5} className="d8-ring">
            <span className="mono">{Math.max(0, Math.round(final.submitRemaining))}s</span>
          </CountdownRing>
        )}
      </div>
      {call?.decline_reason && <span className="d8-final-note">Motivo: {call.decline_reason}</span>}
      {final.duplicateBlocked && <span className="d8-final-note warn">Envío duplicado bloqueado</span>}
    </animated.div>
  );
}

export default function Design8({ items, turnItems, intent, call, phase }) {
  const cards = buildInsightCards(items, intent);
  const cardTransitions = useTransition(cards, {
    keys: (c) => c.id,
    from: { opacity: 0, transform: "translateX(16px)" },
    enter: { opacity: 1, transform: "translateX(0px)" },
    update: { opacity: 1, transform: "translateX(0px)" },
    config: { tension: 240, friction: 26 },
  });

  return (
    <div className="design8-root">
      <div className="d8-vignette" aria-hidden="true" />
      <div className="d8-shell">
        <aside className="d8-left">
          <Duration call={call} />
          <Orb phase={phase} />
          <ToolSquare items={items} />
        </aside>

        <main className="d8-main">
          <Chat items={turnItems} />
        </main>

        <aside className="d8-right">
          <div className="d8-insight-list">
            {cards.length === 0 && <p className="d8-empty">Sin información extraída todavía.</p>}
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
