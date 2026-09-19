import { toolMeta } from "../lib/tools";

function summarize(value) {
  if (value === null || value === undefined || value === "") return null;
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  return text.length > 42 ? `${text.slice(0, 39)}…` : text;
}

function fields(record) {
  if (!record || typeof record !== "object") return [];
  return Object.entries(record)
    .map(([key, value]) => [key, summarize(value)])
    .filter(([, value]) => value !== null);
}

// One compressed row per tool call for the log's stack — name, live ms
// while it's running, and just enough of the input/output to recognise the
// call without opening anything. The running row picks up colour and
// pulses gently (see .used-tool.status-running in design11.css) so it
// reads as "happening now" against the finished rows around it.
export default function UsedToolCard({ tool, now, IconComponent }) {
  const meta = toolMeta(tool.tool);
  const running = tool.status === "running";
  const startedMs = tool.ts ? new Date(tool.ts).getTime() : null;
  const elapsed = running && startedMs != null ? Math.max(0, now - startedMs) : tool.ms;

  const inputs = fields(tool.args);
  const outputs = tool.error ? [["error", summarize(tool.error)]] : fields(tool.result);

  return (
    <div className={`used-tool status-${tool.status}`}>
      <div className="used-tool-head">
        <span className="used-tool-icon">
          {IconComponent ? <IconComponent name={tool.tool} size={13} /> : meta.icon}
        </span>
        <span className="used-tool-name">{meta.label}</span>
        <span className="used-tool-ms">{elapsed != null ? `${Math.round(elapsed)} ms` : "—"}</span>
      </div>
      {(inputs.length > 0 || outputs.length > 0) && (
        <div className="used-tool-body">
          {inputs.length > 0 && (
            <div className="used-tool-row">
              <span className="used-tool-tag">in</span>
              {inputs.map(([key, value]) => (
                <span className="used-tool-kv" key={`in-${key}`}>
                  <b>{key}</b>={value}
                </span>
              ))}
            </div>
          )}
          {outputs.length > 0 && (
            <div className="used-tool-row">
              <span className="used-tool-tag">out</span>
              {outputs.map(([key, value]) => (
                <span className="used-tool-kv" key={`out-${key}`}>
                  <b>{key}</b>={value}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
