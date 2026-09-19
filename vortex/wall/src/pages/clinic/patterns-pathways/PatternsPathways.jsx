import { useState } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Patterns from "../patterns/Patterns";
import Pathways from "../pathways/Pathways";
import "./patterns-pathways.css";

// Linked from the Sidebar as "Pathways & Patterns" — the shared home for both
// builders, switched with the toggle below. Each editor also stays reachable
// on its own at /clinic/patterns and /clinic/pathways (see AppRouter.jsx),
// unchanged by this wrapper.

const MODES = [
  {
    key: "pathways",
    label: "Pathways",
    blurb:
      "Puts a patient on the treatment path they need to follow from their very first call, funneling them straight to it based on what they ask for directly.",
  },
  {
    key: "patterns",
    label: "Patterns",
    blurb:
      "Automatically finds patterns in a patient's own call/visit history and suggests a next step. It runs retroactively — after the events already happened.",
  },
];

export default function PatternsPathways() {
  const [mode, setMode] = useState("pathways");
  const active = MODES.find((m) => m.key === mode);

  return (
    <div className="pp-page">
      <SectionHeader
        eyebrow="Builder"
        title="Pathways & Patterns"
        subtitle="Two ways to route a patient"
        action={
          <div className="pp-toggle-row">
            <p className="pp-toggle-blurb">{active.blurb}</p>
            <div className="pp-toggle" role="group" aria-label="Switch between Pathways and Patterns">
              {MODES.map((m) => (
                <button
                  key={m.key}
                  type="button"
                  className={`pp-toggle-btn ${mode === m.key ? "on" : ""}`}
                  onClick={() => setMode(m.key)}
                  aria-pressed={mode === m.key}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>
        }
      />

      <div className="pp-body">
        {mode === "patterns" ? <Patterns /> : <Pathways />}
      </div>
    </div>
  );
}
