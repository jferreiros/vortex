import { useTransition, animated } from "@react-spring/web";

function Bubble({ item }) {
  const isUser = item.role === "user";
  return (
    <div className={`bubble turn-bubble ${isUser ? "user" : "assistant"}`}>
      <span className="who">{isUser ? "Paciente" : "Agente"}</span>
      <p>{item.text}</p>
    </div>
  );
}

// The middle column: pure conversation, no tool chatter — the left pane's
// orb and square already carry that.
export default function ChatColumn({ items }) {
  const transitions = useTransition(items, {
    keys: (item) => item.id,
    from: { opacity: 0, transform: "translateY(28px) scale(0.96)" },
    enter: { opacity: 1, transform: "translateY(0px) scale(1)" },
    update: { opacity: 1, transform: "translateY(0px) scale(1)" },
    config: { tension: 280, friction: 26 },
  });

  return (
    <div className="chat-col">
      <header className="chat-head">
        <span className="dot-live" />
        Transcripción
      </header>
      <div className="chat-stream">
        {items.length === 0 && <p className="chat-empty">Esperando a que empiece la llamada…</p>}
        {transitions((style, item) => (
          <animated.div style={style} className="chat-row">
            <Bubble item={item} />
          </animated.div>
        ))}
      </div>
    </div>
  );
}
