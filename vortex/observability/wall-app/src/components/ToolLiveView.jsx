import { toolMeta } from "../lib/tools";

// The square's content for a running/just-finished tool that has no big
// stage demo: just its inputs and whatever output has landed.
export default function ToolLiveView({ tool }) {
  const meta = toolMeta(tool.tool);
  const args = tool.args || {};
  const inputs = Object.entries(args).filter(([, v]) => v !== null && v !== undefined && v !== "");
  const result = tool.result || {};
  const outputs = tool.error ? [] : Object.entries(result);

  return (
    <div className="tool-live">
      <div className="tool-live-head">
        <span className="tool-live-icon">{meta.icon}</span>
        <span className="tool-live-label">{meta.label}</span>
        <span className={`tool-live-status status-${tool.status}`}>
          {tool.status === "running" ? "en curso…" : tool.status === "ok" ? "completado" : "error"}
        </span>
      </div>
      <div className="stage-section">
        <h4>Entrada</h4>
        <div className="stage-chips">
          {inputs.length === 0 && <span className="stage-empty-inline">Sin parámetros.</span>}
          {inputs.map(([key, value]) => (
            <span className="chip" key={key}>
              <b>{key}</b>: {String(value)}
            </span>
          ))}
        </div>
      </div>
      <div className="stage-section stage-section-grow">
        <h4>Salida</h4>
        {tool.status === "running" && <span className="stage-empty-inline">Esperando resultado…</span>}
        {tool.status !== "running" && (
          <div className="stage-chips">
            {tool.error && <span className="chip warn">{tool.error}</span>}
            {!tool.error && outputs.length === 0 && (
              <span className="stage-empty-inline">Sin datos de salida.</span>
            )}
            {!tool.error &&
              outputs.map(([key, value]) => (
                <span className="chip" key={key}>
                  <b>{key}</b>: {typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)}
                </span>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
