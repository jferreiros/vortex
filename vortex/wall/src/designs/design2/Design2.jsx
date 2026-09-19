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
import WaitingIllustration from "./WaitingIllustration";
import "./design2.css";

const CALL_CAP_SECONDS = 180;
const CARD_TONE = { intent: "coral", patient: "teal", care: "gold", zone: "plum" };

const PHASE_LABEL = {
  connecting: "Conectando…",
  thinking: "Pensando",
  speaking: "Hablando",
  working: "Ejecutando herramienta",
  listening: "Escuchando",
  ended: "Llamada terminada",
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
    <div className="d2-duration">
      <div className="d2-duration-head">
        <span className="d2-kicker">Duración</span>
        <span className="d2-duration-value">
          {formatClock(elapsed)} <span>/ {formatClock(CALL_CAP_SECONDS)}</span>
        </span>
      </div>
      <div className="d2-duration-track">
        <div className={`d2-duration-fill ${ratio > 0.8 ? "warn" : ""}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      {(call.language || call.idle_count > 0) && (
        <div className="d2-duration-chips">
          {call.language && <span className="d2-pill">{LANGUAGE_LABEL[call.language] || call.language}</span>}
          {call.idle_count > 0 && <span className="d2-pill warn">{call.idle_count}× silencio</span>}
        </div>
      )}
    </div>
  );
}

function Orb({ phase }) {
  const active = phase === "speaking" || phase === "working";
  const breathe = useSpring({
    loop: active ? { reverse: true } : false,
    from: { scale: 0.94 },
    to: { scale: active ? 1.08 : 1.0 },
    config: { duration: phase === "working" ? 620 : 1200 },
  });

  return (
    <div className={`d2-orb-zone phase-${phase}`}>
      <span className="d2-orb-deco dot-1" />
      <span className="d2-orb-deco dot-2" />
      <span className="d2-orb-deco arc" />
      <animated.div className="d2-blob" style={breathe}>
        <PhaseIcon phase={phase} size={34} className="d2-blob-icon" />
      </animated.div>
      <div className="d2-orb-label">{PHASE_LABEL[phase] || phase}</div>
    </div>
  );
}

function ToolSquare({ items }) {
  const focus = deriveToolFocus(items);
  const tone = focus.tool ? toneFor(focus.tool.tool) : "coral";

  return (
    <div className={`d2-tool-card tone-${tone}`}>
      <span className="d2-kicker">
        {focus.mode === "recent" ? "Últimas herramientas" : "Demo en directo"}
      </span>
      <div className="d2-tool-card-body">
        {focus.mode === "stage" && <Stage tool={focus.tool} IconComponent={ToolIcon} />}
        {focus.mode === "live" && <ToolLiveView tool={focus.tool} IconComponent={ToolIcon} />}
        {focus.mode === "recent" && <RecentToolsList items={focus.recent} IconComponent={ToolIcon} />}
      </div>
    </div>
  );
}

function toneFor(toolName) {
  const tones = ["coral", "teal", "gold", "plum"];
  let hash = 0;
  for (const ch of toolName) hash = (hash * 31 + ch.charCodeAt(0)) % tones.length;
  return tones[hash];
}

function Chat({ items }) {
  const transitions = useTransition(items, {
    keys: (item) => item.id,
    from: { opacity: 0, transform: "translateY(20px) scale(0.98)" },
    enter: { opacity: 1, transform: "translateY(0px) scale(1)" },
    update: { opacity: 1, transform: "translateY(0px) scale(1)" },
    config: { tension: 300, friction: 28 },
  });

  return (
    <div className="d2-chat">
      <header className="d2-chat-head">
        <span className="d2-chat-title">Transcripción</span>
        <span className="d2-live-tag">
          <span className="d2-dot-live" /> en vivo
        </span>
      </header>
      <div className="d2-chat-stream">
        {items.length === 0 && (
          <div className="d2-waiting">
            <WaitingIllustration />
            <p>Esperando a que empiece la llamada…</p>
          </div>
        )}
        {transitions((style, item) => {
          const isUser = item.role === "user";
          return (
            <animated.div style={style} className={`d2-row ${isUser ? "user" : "assistant"}`}>
              <span className={`d2-avatar ${isUser ? "user" : "assistant"}`}>{isUser ? "P" : "V"}</span>
              <div className={`d2-bubble ${isUser ? "user" : "assistant"}`}>
                <p>{item.text}</p>
              </div>
            </animated.div>
          );
        })}
      </div>
    </div>
  );
}

const CARD_ICON = { intent: "flag", patient: "id", care: "care", zone: "pin" };

function CardGlyph({ id }) {
  const kind = CARD_ICON[id] || "flag";
  const paths = {
    flag: <path d="M6 3v18M6 4h11l-3 4l3 4H6" />,
    id: <><rect x="4" y="6" width="16" height="12" rx="2" /><circle cx="9.5" cy="11.5" r="1.8" /><path d="M14 10.5h4M14 13.5h4M7 16h6" /></>,
    care: <><path d="M12 20s-7-4.4-7-10a4.5 4.5 0 0 1 7-3.7A4.5 4.5 0 0 1 19 10c0 5.6-7 10-7 10z" /></>,
    pin: <><path d="M12 21s7-6.3 7-11.5A7 7 0 0 0 5 9.5C5 14.7 12 21 12 21z" /><circle cx="12" cy="9.5" r="2.4" /></>,
  };
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      {paths[kind]}
    </svg>
  );
}

function InsightCard({ card }) {
  const tone = CARD_TONE[card.id] || "coral";
  return (
    <div className={`d2-insight-card tone-${tone}`}>
      <span className="d2-insight-glyph">
        <CardGlyph id={card.id} />
      </span>
      <div className="d2-insight-copy">
        <span className="d2-insight-title">{card.title}</span>
        <span className="d2-insight-value">{card.value}</span>
        {card.rule && <span className="d2-insight-rule">{card.rule}</span>}
      </div>
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
    <animated.div style={pop} className={`d2-final ${final.accepted ? "done" : ""}`}>
      <div className="d2-final-row">
        <div>
          <span className="d2-kicker on-dark">Acción final</span>
          <span className="d2-final-value">{final.label}</span>
        </div>
        {final.showCountdown && (
          <CountdownRing ratio={ratio} size={44} stroke={3.5} className="d2-ring">
            <span className="d2-ring-text">{Math.max(0, Math.round(final.submitRemaining))}s</span>
          </CountdownRing>
        )}
      </div>
      {call?.decline_reason && <span className="d2-final-note">Motivo: {call.decline_reason}</span>}
      {final.duplicateBlocked && <span className="d2-final-note warn">Envío duplicado bloqueado</span>}
    </animated.div>
  );
}

export default function Design2({ items, turnItems, intent, call, phase }) {
  const cards = buildInsightCards(items, intent);
  const cardTransitions = useTransition(cards, {
    keys: (c) => c.id,
    from: { opacity: 0, transform: "translateX(18px) scale(0.96)" },
    enter: { opacity: 1, transform: "translateX(0px) scale(1)" },
    update: { opacity: 1, transform: "translateX(0px) scale(1)" },
    config: { tension: 250, friction: 25 },
  });

  return (
    <div className={`design2-root phase-${phase}`}>
      <div className="d2-ambient" aria-hidden="true">
        <span className="d2-float f1" />
        <span className="d2-float f2" />
        <span className="d2-float f3" />
      </div>
      <div className="d2-shell">
        <aside className="d2-left">
          <Duration call={call} />
          <Orb phase={phase} />
          <ToolSquare items={items} />
        </aside>

        <main className="d2-main">
          <Chat items={turnItems} />
        </main>

        <aside className="d2-right">
          <div className="d2-insight-list">
            {cards.length === 0 && <p className="d2-empty">Sin información extraída todavía.</p>}
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
