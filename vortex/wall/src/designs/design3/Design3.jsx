import { useEffect, useState } from "react";
import { useSpring, useTransition, animated } from "@react-spring/web";
import { formatClock } from "../../lib/dates";
import { LANGUAGE_LABEL, STATUS_LABEL } from "../../lib/labels";
import { PhaseIcon, ToolIcon } from "../../lib/icons";
import { buildInsightCards, deriveFinalAction, deriveToolFocus } from "../../lib/derive";
import CountdownRing from "../../components/CountdownRing";
import Stage from "../../components/Stage";
import ToolLiveView from "../../components/ToolLiveView";
import RecentToolsList from "../../components/RecentToolsList";
import "./design3.css";

const CALL_CAP_SECONDS = 180;

const PHASE_LABEL = {
  connecting: "Conectando",
  thinking: "Pensando",
  speaking: "Hablando",
  working: "Ejecutando herramienta",
  listening: "Escuchando",
  ended: "Llamada finalizada",
};

// Fixed anchor points around the orb. Whichever cards exist right now
// (intent, patient, care, zone) claim the first N anchors in that order —
// the layout never has a "hole" where a missing card would have been.
const ANCHORS = ["top-left", "top-right", "bottom-left", "bottom-right"];

function useTicker() {
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
}

function TopBar({ call }) {
  useTicker();
  const startedMs = call?.started_at ? new Date(call.started_at).getTime() : null;
  const elapsed = call
    ? call.live
      ? startedMs
        ? (Date.now() - startedMs) / 1000
        : 0
      : (call.duration_ms ?? 0) / 1000
    : 0;

  return (
    <header className="d3-topbar">
      <div className="d3-topbar-brand">
        <span className="d3-brand-mark" />
        Clínica Arenal
      </div>
      <div className="d3-topbar-meta">
        {call?.language && <span className="d3-meta-pill">{LANGUAGE_LABEL[call.language] || call.language}</span>}
        {call?.idle_count > 0 && <span className="d3-meta-pill warn">{call.idle_count}× silencio</span>}
        <span className="d3-meta-pill mono">
          {formatClock(elapsed)} / {formatClock(CALL_CAP_SECONDS)}
        </span>
      </div>
    </header>
  );
}

function InsightOrbit({ cards }) {
  const placed = cards.slice(0, ANCHORS.length).map((card, i) => ({ ...card, anchor: ANCHORS[i] }));
  const transitions = useTransition(placed, {
    keys: (c) => c.id,
    from: { opacity: 0, transform: "scale(0.7)" },
    enter: { opacity: 1, transform: "scale(1)" },
    leave: { opacity: 0, transform: "scale(0.7)" },
    config: { tension: 260, friction: 24 },
  });

  return (
    <div className="d3-orbit">
      {transitions((style, card) => (
        <animated.div style={style} className={`d3-orbit-card anchor-${card.anchor}`}>
          <span className="d3-orbit-title">{card.title}</span>
          <span className="d3-orbit-value">{card.value}</span>
        </animated.div>
      ))}
    </div>
  );
}

function CenterStage({ phase, call, tool }) {
  const ended = call && !call.live;
  const active = phase === "speaking" || phase === "working";

  const ring = useSpring({
    loop: active ? { reverse: true } : false,
    from: { scale: 0.92, opacity: 0.35 },
    to: { scale: active ? 1.32 : 1.08, opacity: active ? 0.7 : 0.28 },
    config: { duration: phase === "working" ? 720 : 1150 },
  });
  const core = useSpring({
    scale: ended ? 1 : active ? 1.05 : 1,
    config: { tension: 190, friction: 20 },
  });

  return (
    <div className={`d3-stage phase-${phase} ${ended ? "ended" : ""}`}>
      <animated.span className="d3-stage-ring" style={ring} />
      <animated.div className="d3-stage-core" style={core}>
        <PhaseIcon phase={phase} size={44} />
      </animated.div>
      <div className="d3-stage-caption">
        <span className="d3-stage-phase">{PHASE_LABEL[phase] || phase}</span>
        {tool && <span className="d3-stage-tool">· {tool}</span>}
      </div>
    </div>
  );
}

function LiveCaption({ items }) {
  const last = items.length ? items[items.length - 1] : null;
  const spring = useSpring({
    key: last?.id ?? "empty",
    from: { opacity: 0, transform: "translateY(8px)" },
    to: { opacity: 1, transform: "translateY(0px)" },
    config: { tension: 280, friction: 28 },
  });

  if (!last) {
    return <p className="d3-caption muted">La transcripción aparecerá aquí en cuanto empiece la llamada.</p>;
  }
  return (
    <animated.p style={spring} className="d3-caption">
      <span className="d3-caption-who">{last.role === "user" ? "Paciente" : "Agente"}</span>
      {last.text}
    </animated.p>
  );
}

const DRAWER_HEIGHT = 520;

function Drawer({ open, onToggle, items, toolFocus }) {
  const spring = useSpring({
    height: open ? DRAWER_HEIGHT : 0,
    config: { tension: 260, friction: 30 },
  });

  return (
    <>
      <button type="button" className="d3-drawer-toggle" onClick={onToggle}>
        {open ? "Ocultar transcripción ↓" : "Ver transcripción completa ↑"}
      </button>
      <animated.div style={spring} className="d3-drawer">
        <div className="d3-drawer-inner">
          <div className="d3-drawer-col">
            <span className="d3-drawer-kicker">Transcripción</span>
            <div className="d3-drawer-chat">
              {items.length === 0 && <p className="muted">Sin turnos todavía.</p>}
              {items.map((item) => (
                <div key={item.id} className={`d3-drawer-turn ${item.role}`}>
                  <span className="who">{item.role === "user" ? "Paciente" : "Agente"}</span>
                  <p>{item.text}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="d3-drawer-col">
            <span className="d3-drawer-kicker">Herramienta</span>
            <div className="d3-drawer-tool">
              {toolFocus.mode === "stage" && <Stage tool={toolFocus.tool} IconComponent={ToolIcon} />}
              {toolFocus.mode === "live" && <ToolLiveView tool={toolFocus.tool} IconComponent={ToolIcon} />}
              {toolFocus.mode === "recent" && <RecentToolsList items={toolFocus.recent} IconComponent={ToolIcon} />}
            </div>
          </div>
        </div>
      </animated.div>
    </>
  );
}

function VerdictBanner({ call }) {
  const final = deriveFinalAction(call);
  const ratio = final.showCountdown ? Math.max(0, final.submitRemaining) / (call?.submit_window_secs ?? 30) : 1;
  const pop = useSpring({
    from: { opacity: 0, transform: "translateY(14px) scale(0.96)" },
    to: { opacity: 1, transform: "translateY(0px) scale(1)" },
    config: { tension: 220, friction: 24 },
  });

  return (
    <animated.div style={pop} className={`d3-verdict ${final.accepted ? "done" : ""}`}>
      <div>
        <span className="d3-verdict-kicker">{STATUS_LABEL[call?.status] ? "Resultado" : "Acción final"}</span>
        <span className="d3-verdict-value">{final.label}</span>
        {call?.decline_reason && <span className="d3-verdict-note">Motivo: {call.decline_reason}</span>}
      </div>
      {final.showCountdown && (
        <CountdownRing ratio={ratio} size={56} stroke={4} className="d3-verdict-ring">
          <span>{Math.max(0, Math.round(final.submitRemaining))}s</span>
        </CountdownRing>
      )}
    </animated.div>
  );
}

export default function Design3({ items, turnItems, intent, call, phase }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const cards = buildInsightCards(items, intent);
  const toolFocus = deriveToolFocus(items);
  const ended = call && !call.live;

  useEffect(() => {
    if (ended) setDrawerOpen(false);
  }, [ended]);

  return (
    <div className={`design3-root phase-${phase}`}>
      <div className="d3-vignette" aria-hidden="true" />
      <TopBar call={call} />

      <div className="d3-center">
        {!ended && (
          <div className="d3-orbit-zone">
            <InsightOrbit cards={cards} />
            <CenterStage
              phase={phase}
              call={call}
              tool={toolFocus.tool ? toolFocus.tool.tool.replaceAll("_", " ") : null}
            />
          </div>
        )}
        {ended && <VerdictBanner call={call} />}
        <div className="d3-caption-zone">
          <LiveCaption items={turnItems} />
        </div>
      </div>

      <Drawer open={drawerOpen} onToggle={() => setDrawerOpen((v) => !v)} items={turnItems} toolFocus={toolFocus} />
    </div>
  );
}
