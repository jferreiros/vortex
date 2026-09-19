import DurationBar from "./DurationBar";
import VoiceOrb from "./VoiceOrb";
import Stage from "./Stage";
import ToolLiveView from "./ToolLiveView";
import RecentToolsList from "./RecentToolsList";
import { toolMeta } from "../lib/tools";

// The square below the orb: while the last thing that happened is a tool
// call (running, or just finished — before the next chat turn arrives), it
// shows that tool live: the big stage demo if the tool has one, otherwise a
// generic inputs/outputs view. Once the conversation has moved on, it falls
// back to a quiet summary of recent calls.
function ToolSquare({ items }) {
  const lastItem = items.length ? items[items.length - 1] : null;
  const showLive = lastItem?.type === "tool";

  if (showLive) {
    const meta = toolMeta(lastItem.tool);
    return meta.big ? <Stage tool={lastItem} /> : <ToolLiveView tool={lastItem} />;
  }

  return <RecentToolsList items={items.filter((it) => it.type === "tool")} />;
}

export default function LeftPane({ items, call, phase }) {
  return (
    <aside className="left-pane">
      <DurationBar call={call} />
      <VoiceOrb phase={phase} big />
      <div className="tool-square">
        <ToolSquare items={items} />
      </div>
    </aside>
  );
}
