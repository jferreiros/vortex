import LeftPane from "../components/LeftPane";
import ChatColumn from "../components/ChatColumn";
import InsightPanel from "../components/InsightPanel";

// The page exactly as it shipped: kept reachable so the redesign never
// regresses the one thing production actually points at today.
export default function DesignOriginal({ items, turnItems, call, phase, intent }) {
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
