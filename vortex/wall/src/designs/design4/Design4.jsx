import { useEffect, useRef, useState } from "react";
import { useSpring, useTransition, animated } from "@react-spring/web";
import { formatClock } from "../../lib/dates";
import { LANGUAGE_LABEL } from "../../lib/labels";
import { PhaseIcon, ToolIcon } from "../../lib/icons";
import { buildInsightCards, deriveFinalAction, deriveToolFocus } from "../../lib/derive";
import CountdownRing from "../../components/CountdownRing";
import Stage from "../../components/Stage";
import ToolLiveView from "../../components/ToolLiveView";
import RecentToolsList from "../../components/RecentToolsList";
import "./design4.css";

const CALL_CAP_SECONDS = 180;
const PHASE_LABEL = {
  connecting: "Conectando",
  thinking: "Pensando",
  speaking: "Hablando",
  working: "Ejecutando herramienta",
  listening: "Escuchando",
  ended: "Finalizada",
};

// Scattered, not gridded — each card gets a fixed canvas slot and a small
// deterministic rotation so the layout reads as "placed" rather than
// aligned. Order is the order cards appear in (intent first, then patient,
// care, zone), reused every render so a card never jumps slots.
const PIN_SLOTS = [
  { top: "8%", left: "62%", rotate: -3, depth: 1 },
  { top: "14%", left: "84%", rotate: 2, depth: 0.85 },
  { top: "68%", left: "80%", rotate: -2, depth: 0.9 },
  { top: "78%", left: "58%", rotate: 3, depth: 0.7 },
];

function hashRotate(id, spread = 4) {
  const s = String(id);
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 1000;
  return (h / 1000) * spread * 2 - spread;
}

function useParallax() {
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const ref = useRef(null);
  useEffect(() => {
    function onMove(e) {
      const x = (e.clientX / window.innerWidth - 0.5) * 2;
      const y = (e.clientY / window.innerHeight - 0.5) * 2;
      setOffset({ x, y });
    }
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, []);
  return offset;
}

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
    <div className="d4-hud-corner top-left">
      <span className="d4-hud-tag">DURACIÓN</span>
      <div className="d4-hud-track">
        <div className={`d4-hud-fill ${ratio > 0.8 ? "warn" : ""}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      <span className="d4-hud-value">
        {formatClock(elapsed)} / {formatClock(CALL_CAP_SECONDS)}
      </span>
      {(call.language || call.idle_count > 0) && (
        <div className="d4-hud-chips">
          {call.language && <span className="d4-hud-chip">{LANGUAGE_LABEL[call.language] || call.language}</span>}
          {call.idle_count > 0 && <span className="d4-hud-chip warn">{call.idle_count}× silencio</span>}
        </div>
      )}
    </div>
  );
}

function Orb({ phase, parallax }) {
  const active = phase === "speaking" || phase === "working";
  const pulse = useSpring({
    loop: active ? { reverse: true } : false,
    from: { scale: 0.92, opacity: 0.3 },
    to: { scale: active ? 1.3 : 1.05, opacity: active ? 0.65 : 0.25 },
    config: { duration: phase === "working" ? 680 : 1100 },
  });
  const tilt = useSpring({
    transform: `translate(-50%, -50%) translate3d(${parallax.x * -10}px, ${parallax.y * -8}px, 0)`,
    config: { tension: 120, friction: 20 },
  });

  return (
    <animated.div className="d4-orb-zone" style={tilt}>
      <animated.span className={`d4-orb-halo phase-${phase}`} style={pulse} />
      <div className="d4-orb-core">
        <PhaseIcon phase={phase} size={32} />
      </div>
      <span className="d4-orb-label">{PHASE_LABEL[phase] || phase}</span>
    </animated.div>
  );
}

function ToolWindow({ items, parallax }) {
  const focus = deriveToolFocus(items);
  const tilt = useSpring({
    transform: `translate3d(${parallax.x * 14}px, ${parallax.y * 10}px, 0) rotate(-1.2deg)`,
    config: { tension: 110, friction: 20 },
  });

  return (
    <animated.div className="d4-window" style={tilt}>
      <div className="d4-window-bar">
        <span className="d4-window-dot r" />
        <span className="d4-window-dot y" />
        <span className="d4-window-dot g" />
        <span className="d4-window-title">
          {focus.mode === "recent" ? "recent_tools.log" : "tool_trace.live"}
        </span>
      </div>
      <div className="d4-window-body">
        {focus.mode === "stage" && <Stage tool={focus.tool} IconComponent={ToolIcon} />}
        {focus.mode === "live" && <ToolLiveView tool={focus.tool} IconComponent={ToolIcon} />}
        {focus.mode === "recent" && <RecentToolsList items={focus.recent} IconComponent={ToolIcon} />}
      </div>
    </animated.div>
  );
}

function InsightPins({ cards, parallax }) {
  const transitions = useTransition(cards, {
    keys: (c) => c.id,
    from: { opacity: 0, transform: "scale(0.6)" },
    enter: { opacity: 1, transform: "scale(1)" },
    leave: { opacity: 0, transform: "scale(0.6)" },
    config: { tension: 240, friction: 22 },
  });

  return (
    <>
      {transitions((style, card) => {
        const idx = cards.findIndex((c) => c.id === card.id);
        const slot = PIN_SLOTS[idx] || PIN_SLOTS[PIN_SLOTS.length - 1];
        return (
          <animated.div
            key={card.id}
            style={{
              ...style,
              top: slot.top,
              left: slot.left,
              "--depth": slot.depth,
              transform: `translate3d(${parallax.x * 18 * slot.depth}px, ${parallax.y * 14 * slot.depth}px, 0) rotate(${slot.rotate}deg)`,
            }}
            className="d4-pin"
          >
            <span className="d4-pin-title">{card.title}</span>
            <span className="d4-pin-value">{card.value}</span>
          </animated.div>
        );
      })}
    </>
  );
}

function ChatScatter({ items }) {
  const recent = items.slice(-5);
  const transitions = useTransition(recent, {
    keys: (item) => item.id,
    from: { opacity: 0, transform: "translateY(24px) scale(0.9)" },
    enter: { opacity: 1, transform: "translateY(0px) scale(1)" },
    leave: { opacity: 0, transform: "translateY(-10px) scale(0.94)" },
    config: { tension: 280, friction: 28 },
  });

  return (
    <div className="d4-chat-scatter">
      {recent.length === 0 && <p className="d4-chat-empty">Esperando el primer turno…</p>}
      {transitions((style, item) => {
        const isUser = item.role === "user";
        const rot = hashRotate(item.id);
        return (
          <animated.div
            style={{ ...style, "--rot": `${rot}deg` }}
            className={`d4-note ${isUser ? "user" : "assistant"}`}
          >
            <span className="d4-note-who">{isUser ? "Paciente" : "Agente"}</span>
            <p>{item.text}</p>
          </animated.div>
        );
      })}
    </div>
  );
}

function VerdictSeal({ call }) {
  const final = deriveFinalAction(call);
  const ratio = final.showCountdown ? Math.max(0, final.submitRemaining) / (call?.submit_window_secs ?? 30) : 1;
  const pop = useSpring({
    from: { opacity: 0, transform: "translate(-50%, -50%) scale(0.85) rotate(-2deg)" },
    to: { opacity: 1, transform: "translate(-50%, -50%) scale(1) rotate(-2deg)" },
    config: { tension: 220, friction: 20 },
  });

  return (
    <animated.div style={pop} className={`d4-seal ${final.accepted ? "done" : ""}`}>
      <span className="d4-hud-tag on-dark">Acción final</span>
      <span className="d4-seal-value">{final.label}</span>
      {call?.decline_reason && <span className="d4-seal-note">Motivo: {call.decline_reason}</span>}
      {final.showCountdown && (
        <CountdownRing ratio={ratio} size={48} stroke={3.5} className="d4-ring">
          <span>{Math.max(0, Math.round(final.submitRemaining))}s</span>
        </CountdownRing>
      )}
    </animated.div>
  );
}

export default function Design4({ items, turnItems, intent, call, phase }) {
  const parallax = useParallax();
  const cards = buildInsightCards(items, intent);
  const ended = call && !call.live;

  return (
    <div className="design4-root">
      <div className="d4-field" aria-hidden="true">
        <span className="d4-nebula n1" />
        <span className="d4-nebula n2" />
      </div>

      <Duration call={call} />
      <div className="d4-hud-corner top-right">
        <span className="d4-hud-tag">Clínica Arenal</span>
        <span className="d4-hud-sub">canal de voz · en vivo</span>
      </div>

      <div className="d4-canvas">
        {!ended && (
          <>
            <Orb phase={phase} parallax={parallax} />
            <ToolWindow items={items} parallax={parallax} />
            <InsightPins cards={cards} parallax={parallax} />
          </>
        )}
        {ended && <VerdictSeal call={call} />}
      </div>

      <ChatScatter items={turnItems} />
    </div>
  );
}
