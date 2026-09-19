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
import "./design10.css";

const CALL_CAP_SECONDS = 180;
const PHASE_LABEL = {
  connecting: "CONNECTING…",
  thinking: "PROCESSING…",
  speaking: "TX_AUDIO",
  working: "EXEC_TOOL",
  listening: "RX_AUDIO",
  ended: "SESSION_CLOSED",
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
    <div className="d10-duration">
      <span className="d10-label">[DURATION]</span>
      <div className="d10-duration-track">
        <div className={`d10-duration-fill ${ratio > 0.8 ? "warn" : ""}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      <span className="d10-duration-value">
        {formatClock(elapsed)} / {formatClock(CALL_CAP_SECONDS)}
      </span>
      <div className="d10-duration-chips">
        {call.language && <span className="d10-chip">LANG:{(call.language || "").toUpperCase()}</span>}
        {call.idle_count > 0 && <span className="d10-chip warn">IDLE×{call.idle_count}</span>}
      </div>
    </div>
  );
}

function Orb({ phase }) {
  return (
    <div className="d10-orb-wrap">
      <div className={`d10-orb phase-${phase}`}>
        <span className="d10-orb-sweep" />
        <PhaseIcon phase={phase} size={28} />
      </div>
      <div className="d10-orb-label">{PHASE_LABEL[phase] || phase.toUpperCase()}</div>
    </div>
  );
}

function ToolSquare({ items }) {
  const focus = deriveToolFocus(items);
  return (
    <div className="d10-tool-card">
      <div className="d10-tool-card-head">
        {focus.mode === "recent" ? "[RECENT_CALLS]" : "[LIVE_TRACE]"}
      </div>
      <div className="d10-tool-card-body">
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
    config: { tension: 400, friction: 34 },
  });

  return (
    <div className="d10-chat">
      <header className="d10-chat-head">
        <span className="d10-dot-live" />
        [TRANSCRIPT_STREAM]
      </header>
      <div className="d10-chat-stream">
        {items.length === 0 && <p className="d10-empty">AWAITING_INBOUND_CALL…</p>}
        {transitions((style, item) => {
          const isUser = item.role === "user";
          return (
            <animated.div style={style} className={`d10-row ${isUser ? "user" : "assistant"}`}>
              <span className="d10-prompt">{isUser ? "caller$" : "agent#"}</span>
              <p>{item.text}</p>
            </animated.div>
          );
        })}
      </div>
    </div>
  );
}

function InsightCard({ card }) {
  return (
    <div className="d10-insight-card">
      <span className="d10-insight-title">// {card.title.toUpperCase()}</span>
      <span className="d10-insight-value">{card.value}</span>
      {card.rule && <span className="d10-insight-rule">{card.rule}</span>}
    </div>
  );
}

function FinalAction({ call }) {
  const final = deriveFinalAction(call);
  const ratio = final.showCountdown ? Math.max(0, final.submitRemaining) / (call?.submit_window_secs ?? 30) : 1;
  const pop = useSpring({
    opacity: call ? 1 : 0.6,
    config: { tension: 300, friction: 24 },
  });

  return (
    <animated.div style={pop} className={`d10-final ${final.accepted ? "done" : ""}`}>
      <div className="d10-final-top">
        <div>
          <span className="d10-label">[FINAL_ACTION]</span>
          <span className="d10-final-value">{final.label.toUpperCase()}</span>
        </div>
        {final.showCountdown && (
          <CountdownRing ratio={ratio} size={42} stroke={2} className="d10-ring">
            <span>{Math.max(0, Math.round(final.submitRemaining))}</span>
          </CountdownRing>
        )}
      </div>
      {call?.decline_reason && <span className="d10-final-note">REASON: {call.decline_reason.toUpperCase()}</span>}
      {final.duplicateBlocked && <span className="d10-final-note warn">DUPLICATE_SUBMIT_BLOCKED</span>}
    </animated.div>
  );
}

export default function Design10({ items, turnItems, intent, call, phase }) {
  const cards = buildInsightCards(items, intent);
  const cardTransitions = useTransition(cards, {
    keys: (c) => c.id,
    from: { opacity: 0 },
    enter: { opacity: 1 },
    update: { opacity: 1 },
    config: { tension: 320, friction: 28 },
  });

  return (
    <div className="design10-root">
      <div className="d10-scanlines" aria-hidden="true" />
      <div className="d10-shell">
        <aside className="d10-left">
          <Duration call={call} />
          <Orb phase={phase} />
          <ToolSquare items={items} />
        </aside>

        <main className="d10-main">
          <Chat items={turnItems} />
        </main>

        <aside className="d10-right">
          <span className="d10-label">[EXTRACTED_DATA]</span>
          <div className="d10-insight-list">
            {cards.length === 0 && <p className="d10-empty">NO_DATA_YET</p>}
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
