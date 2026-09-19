import { useSpring, animated } from "@react-spring/web";

// A pseudo voice-activity indicator: no real audio level exists in the log
// yet, so this breathes based on the derived conversation phase instead of
// amplitude — cheap, but reads as "alive".
const PHASE_LABEL = {
  connecting: "Conectando",
  thinking: "Pensando",
  speaking: "Hablando",
  working: "Ejecutando tool",
  listening: "Escuchando",
  ended: "Finalizada",
};

const PHASE_EMOJI = {
  connecting: "📡",
  thinking: "🤔",
  speaking: "🗣️",
  working: "🛠️",
  listening: "👂",
  ended: "✅",
};

export default function VoiceOrb({ phase, big = false }) {
  const active = phase === "speaking" || phase === "working";
  const pulse = useSpring({
    loop: active ? { reverse: true } : false,
    from: { scale: 0.82, opacity: 0.45 },
    to: { scale: active ? 1.3 : 1.05, opacity: active ? 1 : 0.55 },
    config: { duration: phase === "working" ? 650 : 950 },
  });
  const blink = useSpring({
    loop: { reverse: true },
    from: { opacity: 0.3 },
    to: { opacity: active ? 1 : 0.7 },
    config: { duration: active ? 500 : 1400 },
  });

  return (
    <div className={`voice-orb phase-${phase} ${big ? "big" : ""}`}>
      <span className="voice-orb-ring">
        <animated.span className="voice-orb-pulse" style={pulse} />
        <animated.span className="voice-orb-core" style={blink}>
          {PHASE_EMOJI[phase] || "•"}
        </animated.span>
      </span>
      <span className="voice-orb-label">{PHASE_LABEL[phase] || phase}</span>
    </div>
  );
}
