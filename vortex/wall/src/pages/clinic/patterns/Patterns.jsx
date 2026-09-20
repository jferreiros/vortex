import { useEffect, useRef, useState, Fragment } from "react";
import { useLocation } from "react-router-dom";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import Placeholder from "../../../components/ui/Placeholder";
import ShapeIcon from "../../../components/ui/ShapeIcon";
import shapeTypesData from "../../../data/shapeTypes.json";
import patternShapes from "../../../data/patternShapes.json";
import patternsSeed from "../../../data/patterns.json";
import "../pathways/pathways.css";
import "./patterns.css";

// Reached from the Sidebar via the "Pathways & Patterns" toggle page, or
// from the Patient Timeline's "Manage suggestions" button. Configures
// GET/PUT /api/wall/patterns — each pattern is a sequence of shared catalog nodes
// (call / message / visit / condition) plus one suggestion node. Same drag-
// and-drop editor aesthetic as Pathways; patterns have no `when` fields.

const SHAPE_META = {
  call: { label: "Call" },
  message: { label: "Message" },
  visit: { label: "Visit" },
  condition: { label: "Condition" },
};

const FAMILY_EMOJI = { call: "☎️", visit: "🏥", message: "📥", condition: "🔍" };

// Rendering-only labels for the tray's family selector (data/patternShapes.json
// keeps plain text labels; this prefixes them here rather than in the file).
const FAMILY_TRAY_EMOJI = { call: "☎️", message: "💬", visit: "🏥", condition: "🔎" };

const GLYPH_BY_KEY = {};
shapeTypesData.families.forEach((fam) => {
  fam.types.forEach((t) => {
    GLYPH_BY_KEY[`${fam.key}::${t.type}`] = t.emoji;
  });
});

function typeEmoji(family, type) {
  return (type && GLYPH_BY_KEY[`${family}::${type}`]) || FAMILY_EMOJI[family];
}

// Labels for the two parametrized dropdowns, keyed by the id stored on a node.
const APPT_TYPE_LABEL = Object.fromEntries(patternShapes.appointmentTypes.map((a) => [a.id, a.label]));
const SPECIALTY_LABEL = Object.fromEntries(patternShapes.specialties.map((s) => [s.id, s.label]));

// A parametrized type keeps its template string ("<appointment type> visit",
// "time gap", ...) as shape.type; this resolves it to what's actually shown
// once (and if) the node's parameter has been filled in.
function resolveLabel(shape) {
  const template = shape.type || SHAPE_META[shape.family]?.label || "";
  if (shape.param === "appointmentType") {
    const label = APPT_TYPE_LABEL[shape.appointmentType];
    return label ? template.replace("<appointment type>", label) : template;
  }
  if (shape.param === "specialty") {
    const label = SPECIALTY_LABEL[shape.specialty];
    return label ? template.replace("<specialty>", label) : template;
  }
  if (shape.param === "gap") {
    if (shape.gap?.value) return `${shape.gap.value} ${shape.gap.unit || "days"} elapsed`;
    return template;
  }
  return template;
}

// One glyph, total — the exact type's emoji, falling back to the bare
// family emoji when the type isn't decided yet. No family/direction badge
// stacked on top of it; the tray's own selector carries that now.
function ShapeGlyphs({ family, type, emoji }) {
  return <ShapeIcon emoji={emoji || typeEmoji(family, type)} className="pathways-shape-main-emoji" />;
}

const DRAG_MIME = "application/x-pattern-shape";
const REORDER_MIME = "application/x-pattern-node-id";
// A history-event shape belongs on the sequence canvas; a suggestion shape
// belongs in the suggestion slot, never the other way round. A second,
// view-tagged MIME type (set alongside DRAG_MIME, empty payload) lets each
// drop target filter by view during dragover, when getData(DRAG_MIME)
// itself isn't readable yet — the JSON payload's own `view` field is the
// same check repeated at drop time, in case dragover was skipped.
const VIEW_MIME = { history: "application/x-pattern-shape-history", suggestion: "application/x-pattern-shape-suggestion" };

const STORAGE_KEY = "vortex.patterns.v2";

function isValidPattern(p) {
  return p && Array.isArray(p.nodes) && p.suggestionNode?.shape?.family;
}

function loadStoredState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed.patterns) && parsed.patterns.length > 0 && parsed.patterns.every(isValidPattern)) {
      return parsed;
    }
  } catch {
    // corrupt or unavailable storage — wait for the server's copy
  }
  return null;
}

// The bundled seed (data/patterns.json) — read before ever hitting the
// database, which runs slow. Only when this has nothing do we fall back to
// the GET /api/wall/patterns round-trip below.
function loadSeedState() {
  if (
    !Array.isArray(patternsSeed?.patterns) ||
    patternsSeed.patterns.length === 0 ||
    !patternsSeed.patterns.every(isValidPattern)
  ) {
    return null;
  }
  return {
    patterns: patternsSeed.patterns,
    selectedId: patternsSeed.selectedId ?? patternsSeed.patterns[0].id,
    asOf: patternsSeed.asOf ?? null,
    specialtyRecallDays: patternsSeed.specialtyRecallDays || {},
  };
}

function applyPatternsDoc(json, setPatterns, setSelectedId, preferredId) {
  if (!Array.isArray(json?.patterns) || json.patterns.length === 0 || !json.patterns.every(isValidPattern)) {
    return;
  }
  setPatterns(json.patterns);
  const nextId =
    (preferredId && json.patterns.some((p) => p.id === preferredId) && preferredId) ||
    (json.selectedId && json.patterns.some((p) => p.id === json.selectedId) && json.selectedId) ||
    json.patterns[0].id;
  setSelectedId(nextId);
}

function SaveIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
      <path d="M8 4v5h8V4" />
      <rect x="7" y="13" width="10" height="7" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 7h14" />
      <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
      <path d="M7 7l1 13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1l1-13" />
      <path d="M10 11v6M14 11v6" />
    </svg>
  );
}

let uid = 0;
const nextId = (prefix) => `${prefix}-${(uid += 1)}`;

// Turn a tray drag payload into a clean node shape — only the fields that are
// actually set, so the persisted JSON stays tidy. The parameter value itself
// (appointmentType / specialty / gap) is added later, once the user picks it.
function buildShape({ family, type, subfamily, param, emoji }) {
  const shape = { family, type };
  if (subfamily) shape.subfamily = subfamily;
  if (emoji) shape.emoji = emoji;
  if (param) shape.param = param;
  return shape;
}

function makePattern(name) {
  return {
    id: nextId("pat"),
    name,
    enabled: true,
    buildableToday: true,
    nodes: [],
    suggestionNode: {
      shape: { family: "call", subfamily: "outgoing", type: "appointment suggestion" },
      description: "",
      chainLabel: "Suggestion",
    },
  };
}

function DescriptionField({ value, onChange, className = "" }) {
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <input
        type="text"
        className="pathways-description-input"
        autoFocus
        draggable={false}
        defaultValue={value}
        onMouseDown={(e) => e.stopPropagation()}
        onFocus={(e) => e.target.select()}
        onBlur={(e) => {
          onChange(e.target.value.trim());
          setEditing(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") setEditing(false);
        }}
      />
    );
  }

  return (
    <span
      className={`pathways-shape-caption above pathways-description-display ${className}`}
      role="button"
      tabIndex={0}
      onClick={() => setEditing(true)}
      onKeyDown={(e) => {
        if (e.key === "Enter") setEditing(true);
      }}
    >
      {value || "Add description"}
    </span>
  );
}

//: The recall intervals that came with the last loaded patterns document.
//: Module-level because `parameterHint` below is called from deep inside the
//: node renderers, where threading the whole document down would mean a prop
//: on every shape.
let RECALL_DAYS = {};

// Some condition nodes stand in for a value that's configured on the
// document itself (e.g. "time gap" means "> specialtyRecallDays"),
// not a fixed number. Hovering the shape shows what that resolves to per
// specialty, so it doesn't read as an arbitrary/unexplained rule.
function parameterHint(shape) {
  // Only the old-style condition nodes (no explicit gap value on the shape)
  // fall back to the "recall interval by specialty" hint; parametrized ones
  // carry their own number and unit, shown inline instead.
  if (shape.family === "condition" && shape.type === "time gap" && shape.param !== "gap") {
    const days = RECALL_DAYS;
    const values = Object.entries(days)
      .map(([key, value]) => `${key}: ${value} days`)
      .join(" · ");
    return `Recall interval by specialty — ${values}`;
  }
  return null;
}

// Inline editor a parametrized node shows once it lands on the canvas or in
// the suggestion slot. Whatever is picked is merged onto the node's shape by
// `onChange` and persisted with the pattern on Save. `draggable={false}` +
// stopPropagation keep these from starting the node's reorder drag.
function ParamControls({ shape, onChange }) {
  const stop = (e) => e.stopPropagation();
  if (shape.param === "appointmentType") {
    return (
      <select
        className="ui-select patterns-param-select"
        draggable={false}
        value={shape.appointmentType || ""}
        onMouseDown={stop}
        onChange={(e) => onChange({ appointmentType: e.target.value })}
      >
        <option value="" disabled>Pick appointment type</option>
        {patternShapes.appointmentTypes.map((a) => (
          <option key={a.id} value={a.id}>{a.label}</option>
        ))}
      </select>
    );
  }
  if (shape.param === "specialty") {
    return (
      <select
        className="ui-select patterns-param-select"
        draggable={false}
        value={shape.specialty || ""}
        onMouseDown={stop}
        onChange={(e) => onChange({ specialty: e.target.value })}
      >
        <option value="" disabled>Pick specialty</option>
        {patternShapes.specialties.map((s) => (
          <option key={s.id} value={s.id}>{s.label}</option>
        ))}
      </select>
    );
  }
  if (shape.param === "gap") {
    const gap = shape.gap || { unit: "days" };
    return (
      <div className="patterns-param-gap" onMouseDown={stop}>
        <input
          type="number"
          min="1"
          className="patterns-param-num"
          draggable={false}
          placeholder="n"
          value={gap.value ?? ""}
          onChange={(e) =>
            onChange({ gap: { ...gap, value: e.target.value === "" ? "" : Number(e.target.value) } })
          }
        />
        <select
          className="ui-select patterns-param-select"
          draggable={false}
          value={gap.unit || "days"}
          onChange={(e) => onChange({ gap: { ...gap, unit: e.target.value } })}
        >
          {patternShapes.gapUnits.map((u) => (
            <option key={u} value={u}>{u}</option>
          ))}
        </select>
        <span className="patterns-param-suffix">elapsed</span>
      </div>
    );
  }
  return null;
}

function ShapeNode({ node, nodeNumber, onRemove, onDescriptionChange, onShapeChange }) {
  const meta = SHAPE_META[node.shape.family];
  const label = resolveLabel(node.shape) || meta.label;
  const hint = parameterHint(node.shape);
  const title = hint ? `${label}\n${hint}` : label;

  return (
    <div
      className="pathways-shape-node"
      data-step="true"
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(REORDER_MIME, node.id);
        e.dataTransfer.effectAllowed = "move";
      }}
    >
      <span className="pathways-node-index">{`Node ${nodeNumber}`}</span>
      <DescriptionField value={node.description} onChange={onDescriptionChange} />
      <div className="pathways-shape-wrap">
        <button
          type="button"
          className="pathways-shape-remove"
          onClick={onRemove}
          aria-label={`Remove ${label} step`}
        >
          ×
        </button>
        <span
          className={`pathways-shape pathways-shape-${node.shape.family} ${hint ? "patterns-shape-parameterized" : ""}`}
          title={title}
        >
          <ShapeGlyphs family={node.shape.family} type={node.shape.type} emoji={node.shape.emoji} />
        </span>
      </div>
      <span className="patterns-node-type-label">{label}</span>
      {node.shape.param && (
        <div className="patterns-node-params">
          <ParamControls shape={node.shape} onChange={onShapeChange} />
        </div>
      )}
    </div>
  );
}

function SuggestionSlot({ suggestion, onDropShape, onDescriptionChange, onChainLabelChange, onShapeChange }) {
  const [over, setOver] = useState(false);
  const shape = suggestion?.shape;
  const label = shape ? resolveLabel(shape) : "Suggestion";

  return (
    <div className="patterns-suggestion-wrap">
      <div
        className={`patterns-suggestion-slot ${over ? "over" : ""}`}
        data-suggestion-slot="true"
        onDragOver={(e) => {
          // Only a suggestion shape (the "Suggestions" view) belongs here —
          // a history-event shape is rejected even though it shares the
          // same family keys.
          if (!e.dataTransfer.types.includes(VIEW_MIME.suggestion)) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const raw = e.dataTransfer.getData(DRAG_MIME);
          if (!raw) return;
          const shapeData = JSON.parse(raw);
          if (shapeData.view !== "suggestion") return;
          onDropShape(shapeData);
        }}
      >
        {/* A real node's index + description sit above its circle; "Suggest"
            has no description, so this hidden filler goes above the label
            instead of between it and the circle — the circle still lands on
            the same row as the connector arrow and every other shape, but
            "Suggest" stays right on top of its own circle, no gap. */}
        <span className="pathways-shape-caption above" style={{ visibility: "hidden" }} aria-hidden="true">·</span>
        <span className="pathways-node-index">Suggest</span>
        <div className="pathways-shape-wrap">
          <span
            className={`pathways-shape patterns-suggestion-shape ${shape ? `pathways-shape-${shape.family}` : ""}`}
            title={label}
          >
            {shape ? (
              <ShapeGlyphs family={shape.family} type={shape.type} emoji={shape.emoji} />
            ) : (
              <span className="pathways-shape-main-emoji">?</span>
            )}
          </span>
        </div>
        {shape?.param && (
          <div className="patterns-node-params">
            <ParamControls shape={shape} onChange={onShapeChange} />
          </div>
        )}
        <DescriptionField
          value={suggestion?.chainLabel || ""}
          onChange={onChainLabelChange}
          className="patterns-chain-label-field"
        />
      </div>
      <span className="patterns-suggestion-hint">Drop a shape to set the suggestion</span>
    </div>
  );
}

function PatternCanvas({
  pattern,
  onDropShape,
  onReorderNode,
  onRemoveNode,
  onDescriptionChange,
  onNodeShapeChange,
  onSuggestionDrop,
  onSuggestionDescriptionChange,
  onSuggestionChainLabelChange,
  onSuggestionShapeChange,
}) {
  const trackRef = useRef(null);
  const [overIndex, setOverIndex] = useState(null);

  const indexForPoint = (clientX) => {
    const track = trackRef.current;
    if (!track) return pattern.nodes.length;
    const items = Array.from(track.querySelectorAll("[data-step]"));
    for (let i = 0; i < items.length; i += 1) {
      const rect = items[i].getBoundingClientRect();
      if (clientX < rect.left + rect.width / 2) return i;
    }
    return items.length;
  };

  const handleDragOver = (e) => {
    // Don't steal drops meant for the suggestion slot.
    if (e.target.closest?.("[data-suggestion-slot]")) return;
    const isReorder = e.dataTransfer.types.includes(REORDER_MIME);
    // Only a history-event shape belongs on this canvas — a suggestion
    // shape (☎️/💬 under the "Suggestions" view) is rejected here even
    // though it shares the same family keys.
    if (!isReorder && !e.dataTransfer.types.includes(VIEW_MIME.history)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = isReorder ? "move" : "copy";
    setOverIndex(indexForPoint(e.clientX));
  };

  const handleDrop = (e) => {
    if (e.target.closest?.("[data-suggestion-slot]")) return;
    e.preventDefault();
    const nodeId = e.dataTransfer.getData(REORDER_MIME);
    if (nodeId) {
      onReorderNode(nodeId, indexForPoint(e.clientX));
      setOverIndex(null);
      return;
    }
    const raw = e.dataTransfer.getData(DRAG_MIME);
    setOverIndex(null);
    if (!raw) return;
    const shapeData = JSON.parse(raw);
    if (shapeData.view !== "history") return;
    onDropShape(shapeData, indexForPoint(e.clientX));
  };

  return (
    <Card padding="lg" className="pathways-canvas patterns-canvas">
      <div
        className={`pathways-canvas-track ${overIndex != null ? "over" : ""}`}
        ref={trackRef}
        onDragOver={handleDragOver}
        onDragLeave={() => setOverIndex(null)}
        onDrop={handleDrop}
      >
        {pattern.nodes.length === 0 ? (
          <Placeholder
            kind="diagram"
            label="Drag History-event shapes here to build the match sequence"
            minHeight="120px"
            className="pathways-canvas-empty"
          />
        ) : (
          <div className="pathways-timeline">
            <div className="pathways-timeline-bg" aria-hidden="true">
              <span className="pathways-node-index" style={{ visibility: "hidden" }}>·</span>
              <span className="pathways-shape-caption above" style={{ visibility: "hidden" }}>·</span>
              <div className="pathways-timeline-bars">
                {pattern.nodes.map((node) => (
                  <span key={node.id} className="pathways-timeline-bar" />
                ))}
              </div>
            </div>
            {pattern.nodes.map((node, i) => (
              <Fragment key={node.id}>
                {overIndex === i && <span className="pathways-drop-marker" />}
                <ShapeNode
                  node={node}
                  nodeNumber={i + 1}
                  onRemove={() => onRemoveNode(node.id)}
                  onDescriptionChange={(value) => onDescriptionChange(node.id, value)}
                  onShapeChange={(patch) => onNodeShapeChange(node.id, patch)}
                />
              </Fragment>
            ))}
            {overIndex === pattern.nodes.length && (
              <span className="pathways-drop-marker" />
            )}
          </div>
        )}

        <div className="patterns-canvas-arrow-track" aria-hidden="true">
          <span className="pathways-node-index" style={{ visibility: "hidden" }}>·</span>
          <span className="pathways-shape-caption above" style={{ visibility: "hidden" }}>·</span>
          <div className="pathways-shape-wrap">
            <span className="patterns-canvas-arrow">⟶</span>
          </div>
        </div>

        <SuggestionSlot
          suggestion={pattern.suggestionNode}
          onDropShape={onSuggestionDrop}
          onDescriptionChange={onSuggestionDescriptionChange}
          onChainLabelChange={onSuggestionChainLabelChange}
          onShapeChange={onSuggestionShapeChange}
        />
      </div>
    </Card>
  );
}

// Two-level tray: pick a view (History events vs Suggestions), then a family
// within that view, then drag a type. History-event shapes are meant for the
// sequence canvas; Suggestion shapes for the suggestion slot. Types whose name
// carries a placeholder ship a `param`, so a control appears once they land.
function ShapeTray() {
  const [viewKey, setViewKey] = useState(patternShapes.views[0].key);
  const view = patternShapes.views.find((v) => v.key === viewKey) ?? patternShapes.views[0];
  const [familyKey, setFamilyKey] = useState(view.families[0].key);
  const familyDef = view.families.find((f) => f.key === familyKey) ?? view.families[0];

  const selectView = (key) => {
    const next = patternShapes.views.find((v) => v.key === key) ?? patternShapes.views[0];
    setViewKey(key);
    setFamilyKey(next.families[0].key);
  };

  return (
    <Card padding="lg" className="pathways-tray patterns-tray">
      <div className="pathways-tray-families patterns-tray-views">
        {patternShapes.views.map((v) => (
          <button
            key={v.key}
            type="button"
            className={`pathways-tray-family ${viewKey === v.key ? "on" : ""}`}
            onClick={() => selectView(v.key)}
          >
            {v.label}
          </button>
        ))}
      </div>
      <div className="pathways-tray-families">
        {view.families.map((f) => (
          <button
            key={f.key}
            type="button"
            className={`pathways-tray-family ${familyDef.key === f.key ? "on" : ""}`}
            onClick={() => setFamilyKey(f.key)}
          >
            {FAMILY_TRAY_EMOJI[f.key]} {f.label}
          </button>
        ))}
      </div>
      <div className="pathways-tray-types">
        {familyDef.types.map((t) => {
          const subfamily = t.subfamily ?? familyDef.subfamily;
          return (
            <div
              key={t.type}
              className="pathways-tray-shape"
              draggable
              tabIndex={0}
              onDragStart={(e) => {
                e.dataTransfer.setData(
                  DRAG_MIME,
                  JSON.stringify({
                    family: familyDef.key,
                    type: t.type,
                    subfamily,
                    param: t.param,
                    emoji: t.emoji,
                    view: viewKey,
                  })
                );
                e.dataTransfer.setData(VIEW_MIME[viewKey], "1");
                e.dataTransfer.effectAllowed = "copy";
              }}
            >
              <span className={`pathways-shape pathways-shape-${familyDef.key}`}>
                <ShapeGlyphs family={familyDef.key} type={t.type} emoji={t.emoji} />
              </span>
              <span className="pathways-tray-shape-label">{t.type}</span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export default function Patterns() {
  const location = useLocation();
  const [initial] = useState(
    () => loadStoredState() ?? loadSeedState() ?? { patterns: [], selectedId: null }
  );
  const [patterns, setPatterns] = useState(initial.patterns);
  // A pattern detected on a patient's timeline wins the initial selection —
  // that's what "Manage suggestions" is opened to look at — over whatever
  // was last selected here.
  const detectedId = location.state?.patternId;
  const startingId =
    detectedId && initial.patterns.some((p) => p.id === detectedId) ? detectedId : initial.selectedId;
  const [selectedId, setSelectedId] = useState(startingId ?? null);
  // asOf and specialtyRecallDays belong to the document, not to any one
  // pattern; a Save has to put them back or the next load loses them. The
  // local save (STORAGE_KEY) doesn't carry them, so fall back to the seed's
  // — same source of truth we already used for `initial.patterns` above.
  const [docMeta, setDocMeta] = useState(() => {
    const meta = {
      asOf: initial.asOf ?? patternsSeed.asOf ?? null,
      specialtyRecallDays: initial.specialtyRecallDays || patternsSeed.specialtyRecallDays || {},
    };
    RECALL_DAYS = meta.specialtyRecallDays;
    return meta;
  });
  const [renamingId, setRenamingId] = useState(null);
  const [saveStatus, setSaveStatus] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  useEffect(() => {
    // The cache or the bundled seed already has patterns to show — skip the
    // database round-trip entirely rather than wait on it.
    if (initial.patterns.length > 0) return;
    let cancelled = false;
    fetch("/api/wall/patterns")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((json) => {
        if (cancelled) return;
        RECALL_DAYS = json?.specialtyRecallDays || {};
        setDocMeta({
          asOf: json?.asOf ?? null,
          specialtyRecallDays: json?.specialtyRecallDays || {},
        });
        applyPatternsDoc(json, setPatterns, setSelectedId, detectedId);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [initial]);

  const selected = patterns.find((p) => p.id === selectedId) ?? patterns[0];

  const handleCreate = () => {
    const pat = makePattern("Untitled pattern");
    setPatterns((prev) => [...prev, pat]);
    setSelectedId(pat.id);
    setRenamingId(pat.id);
  };

  const handleDeletePattern = () => {
    const index = patterns.findIndex((p) => p.id === selectedId);
    const next = patterns.filter((p) => p.id !== selectedId);
    setPatterns(next);
    const fallback = next[Math.max(0, index - 1)] ?? next[0];
    if (fallback) setSelectedId(fallback.id);
    setShowDeleteConfirm(false);
  };

  const commitRename = (id, rawName) => {
    const name = rawName.trim();
    setPatterns((prev) => prev.map((p) => (p.id === id ? { ...p, name: name || "Untitled pattern" } : p)));
    setRenamingId(null);
  };

  const handleDropShape = (shapeData, index) => {
    setPatterns((prev) =>
      prev.map((p) => {
        if (p.id !== selectedId) return p;
        const nodes = [...p.nodes];
        nodes.splice(index, 0, {
          id: nextId("node"),
          shape: buildShape(shapeData),
          description: "",
        });
        return { ...p, nodes };
      })
    );
  };

  const handleNodeShapeChange = (nodeId, patch) => {
    setPatterns((prev) =>
      prev.map((p) => {
        if (p.id !== selectedId) return p;
        const nodes = p.nodes.map((n) =>
          n.id === nodeId ? { ...n, shape: { ...n.shape, ...patch } } : n
        );
        return { ...p, nodes };
      })
    );
  };

  const handleReorderNode = (nodeId, dropIndex) => {
    setPatterns((prev) =>
      prev.map((p) => {
        if (p.id !== selectedId) return p;
        const nodes = [...p.nodes];
        const fromIndex = nodes.findIndex((n) => n.id === nodeId);
        if (fromIndex === -1) return p;
        const [moved] = nodes.splice(fromIndex, 1);
        const insertAt = fromIndex < dropIndex ? dropIndex - 1 : dropIndex;
        nodes.splice(insertAt, 0, moved);
        return { ...p, nodes };
      })
    );
  };

  const handleRemoveNode = (nodeId) => {
    setPatterns((prev) =>
      prev.map((p) => (p.id === selectedId ? { ...p, nodes: p.nodes.filter((n) => n.id !== nodeId) } : p))
    );
  };

  const handleUpdateDescription = (nodeId, description) => {
    setPatterns((prev) =>
      prev.map((p) => {
        if (p.id !== selectedId) return p;
        const nodes = p.nodes.map((n) => (n.id === nodeId ? { ...n, description } : n));
        return { ...p, nodes };
      })
    );
  };

  const handleSuggestionDrop = (shapeData) => {
    setPatterns((prev) =>
      prev.map((p) => {
        if (p.id !== selectedId) return p;
        return {
          ...p,
          suggestionNode: {
            ...p.suggestionNode,
            shape: buildShape(shapeData),
            chainLabel: p.suggestionNode?.chainLabel || shapeData.type,
          },
        };
      })
    );
  };

  const handleSuggestionShapeChange = (patch) => {
    setPatterns((prev) =>
      prev.map((p) =>
        p.id === selectedId
          ? { ...p, suggestionNode: { ...p.suggestionNode, shape: { ...p.suggestionNode.shape, ...patch } } }
          : p
      )
    );
  };

  const handleSuggestionDescription = (description) => {
    setPatterns((prev) =>
      prev.map((p) =>
        p.id === selectedId
          ? { ...p, suggestionNode: { ...p.suggestionNode, description } }
          : p
      )
    );
  };

  const handleSuggestionChainLabel = (chainLabel) => {
    setPatterns((prev) =>
      prev.map((p) =>
        p.id === selectedId
          ? { ...p, suggestionNode: { ...p.suggestionNode, chainLabel } }
          : p
      )
    );
  };

  const handleToggleEnabled = (enabled) => {
    setPatterns((prev) => prev.map((p) => (p.id === selectedId ? { ...p, enabled } : p)));
  };

  const handleSave = async () => {
    const payload = {
      patterns,
      selectedId,
      asOf: docMeta.asOf,
      specialtyRecallDays: docMeta.specialtyRecallDays,
    };
    try {
      const response = await fetch("/api/wall/patterns", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ patterns, selectedId }));
      } catch {
        /* cache is optional */
      }
      setSaveStatus("saved");
    } catch {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ patterns, selectedId }));
        setSaveStatus("saved");
      } catch {
        /* in-memory state still works */
      }
    }
    setTimeout(() => setSaveStatus(null), 2000);
  };

  // First render, before either localStorage or the /api/wall/patterns
  // fetch has produced a pattern to select — render a loading state instead
  // of crashing on `selected.name` below.
  if (!selected) {
    return (
      <div className="pathways-page patterns-page">
        <Placeholder kind="diagram" label="Loading patterns…" minHeight="200px" />
      </div>
    );
  }

  return (
    <div className="pathways-page patterns-page">
      <div className="ui-section-header">
        <div className="pathways-header-actions">
          <span className="ui-section-eyebrow pathways-current-label">Currently editing</span>
          {renamingId === selectedId ? (
            <input
              className="pathways-rename-input"
              autoFocus
              defaultValue={selected.name}
              onFocus={(e) => e.target.select()}
              onBlur={(e) => commitRename(selected.id, e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
                if (e.key === "Escape") setRenamingId(null);
              }}
            />
          ) : (
            <select
              className="ui-select pathways-select"
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              {patterns.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          )}
          <button
            type="button"
            className="pathways-rename-btn"
            onClick={() => setRenamingId(selectedId)}
            aria-label="Rename pattern"
            title="Rename pattern"
          >
            ✎
          </button>
          <label className="patterns-enabled-toggle" title="Enable or disable this pattern">
            <input
              type="checkbox"
              checked={!!selected.enabled}
              onChange={(e) => handleToggleEnabled(e.target.checked)}
            />
            On
          </label>
          <button
            type="button"
            className="pathways-delete-btn"
            onClick={() => setShowDeleteConfirm(true)}
            disabled={patterns.length <= 1}
            aria-label="Delete pattern"
            title={patterns.length <= 1 ? "Can't delete the only pattern" : "Delete pattern"}
          >
            <TrashIcon />
          </button>
          <button
            type="button"
            className={`pathways-save-btn ${saveStatus === "saved" ? "saved" : ""}`}
            onClick={handleSave}
            aria-label="Save changes"
            title={saveStatus === "saved" ? "Saved" : "Save changes"}
          >
            <SaveIcon />
          </button>
          <Button variant="secondary" className="pathways-header-create-btn" onClick={handleCreate}>
            + Create a new pattern
          </Button>
        </div>
      </div>

      {!selected.buildableToday && (
        <span className="patterns-badge needs-log">Needs future call log</span>
      )}

      <div className="pathways-main">
        <PatternCanvas
          pattern={selected}
          onDropShape={handleDropShape}
          onReorderNode={handleReorderNode}
          onRemoveNode={handleRemoveNode}
          onDescriptionChange={handleUpdateDescription}
          onNodeShapeChange={handleNodeShapeChange}
          onSuggestionDrop={handleSuggestionDrop}
          onSuggestionDescriptionChange={handleSuggestionDescription}
          onSuggestionChainLabelChange={handleSuggestionChainLabel}
          onSuggestionShapeChange={handleSuggestionShapeChange}
        />
        <ShapeTray />
      </div>

      {showDeleteConfirm && (
        <div className="ui-modal-overlay" onClick={() => setShowDeleteConfirm(false)}>
          <div className="ui-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ui-modal-head">
              <h3>Delete pattern</h3>
              <button className="ui-modal-close" onClick={() => setShowDeleteConfirm(false)}>✕</button>
            </div>
            <div className="ui-modal-body">
              <p>Delete “{selected.name}”? This can't be undone.</p>
            </div>
            <div className="ui-modal-actions">
              <Button variant="ghost" onClick={() => setShowDeleteConfirm(false)}>Cancel</Button>
              <Button variant="primary" onClick={handleDeletePattern}>Delete</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
