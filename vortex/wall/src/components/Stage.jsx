import { useSpring, animated } from "@react-spring/web";
import { toolMeta } from "../lib/tools";
import StageFindPatient from "./StageFindPatient";
import StageFindSlots from "./StageFindSlots";

// Big-tool demos live here. App.jsx keeps handing this the same tool object
// once it finishes — it stays frozen on screen until a *different* big tool
// starts running, never resets to the empty state on its own.
const STAGE_VIEWS = {
  find_patient: StageFindPatient,
  find_slots: StageFindSlots,
};

export default function Stage({ tool, IconComponent }) {
  const running = tool?.status === "running";
  const failed = tool?.status === "fail";

  const ring = useSpring({
    loop: running ? { reverse: true } : false,
    from: { scale: 0.85, opacity: 0.35 },
    to: {
      scale: running ? 1.15 : failed ? 0.92 : 1.3,
      opacity: running ? 0.85 : 0,
    },
    config: { duration: running ? 900 : 550 },
  });

  const pop = useSpring({
    opacity: tool ? 1 : 0,
    transform: tool ? "scale(1) translateY(0px)" : "scale(0.7) translateY(14px)",
    config: { tension: 260, friction: 24 },
  });

  const meta = tool ? toolMeta(tool.tool) : null;
  const DetailView = tool ? STAGE_VIEWS[tool.tool] : null;

  return (
    <section className="stage">
      <header className="stage-head">Demo en directo</header>
      <div className="stage-body">
        {!tool && <p className="stage-empty">Esperando una herramienta con demo grande…</p>}
        {tool && (
          <div className="stage-layout">
            <animated.div className="stage-figure" style={pop}>
              <animated.span className={`stage-ring ${failed ? "fail" : ""}`} style={ring} />
              <span className="stage-icon">
                {IconComponent ? <IconComponent name={tool.tool} /> : meta.icon}
              </span>
              <span className="stage-label">{meta.label}</span>
              <span className="stage-status">
                {tool.status === "running" ? "en curso…" : tool.status === "ok" ? "completado" : "error"}
              </span>
            </animated.div>
            {DetailView && <DetailView tool={tool} />}
          </div>
        )}
      </div>
    </section>
  );
}
