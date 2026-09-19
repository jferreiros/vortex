import ChatColumn from "./components/ChatColumn";
import LeftPane from "./components/LeftPane";
import InsightPanel from "./components/InsightPanel";
import { useCallTimeline } from "./lib/useCallTimeline";
import "./app.css";

// "demo" (and no id at all) mean: run the scripted loop, not a real poll.
// A real call_id never legitimately equals the literal string "demo".
function getCallId() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  const idx = parts.indexOf("call");
  const params = new URLSearchParams(window.location.search);
  const raw = (idx >= 0 && parts[idx + 1] ? decodeURIComponent(parts[idx + 1]) : null) || params.get("call_id");
  if (!raw || raw === "demo") return null;
  return raw;
}

// Derived, not logged: which of five phases the call is in right now, purely
// from the shape of the last timeline item. Feeds the left pane's voice orb.
function derivePhase(items, call) {
  if (call && !call.live && call.ended_at) return "ended";
  if (items.length === 0) return "connecting";
  const last = items[items.length - 1];
  if (last.type === "tool") return last.status === "running" ? "working" : "thinking";
  if (last.type === "turn") return last.role === "assistant" ? "speaking" : "listening";
  return "connecting";
}

export default function App() {
  const callId = getCallId();
  const { items, intent, call } = useCallTimeline(callId);
  const phase = derivePhase(items, call);
  const turnItems = items.filter((it) => it.type === "turn");

  return (
    <div className="wall-page">
      <div className="app-shell">
        <LeftPane items={items} call={call} phase={phase} />
        <main className="chat-pane">
          <ChatColumn items={turnItems} />
        </main>
        <InsightPanel items={items} intent={intent} call={call} />
      </div>
    </div>
  );
}
