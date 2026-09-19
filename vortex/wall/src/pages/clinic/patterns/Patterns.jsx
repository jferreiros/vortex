import { useEffect, useRef, useState, Fragment } from "react";
import { useLocation } from "react-router-dom";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import Placeholder from "../../../components/ui/Placeholder";
import patternsSeed from "../../../data/patterns.json";
import shapeTypesData from "../../../data/shapeTypes.json";
import "../pathways/pathways.css";
import "./patterns.css";

// Reached from the Sidebar via the "Pathways & Patterns" toggle page, or
// from the Patient Timeline's "Manage suggestions" button. Configures
// src/data/patterns.json — each pattern is a sequence of shared catalog nodes
// (call / message / visit / condition) plus one suggestion node. Same drag-
// and-drop editor aesthetic as Pathways; patterns have no `when` fields.

const SHAPE_META = {
  call: { label: "Call" },
  message: { label: "Message" },
  visit: { label: "Visit" },
  condition: { label: "Condition" },
};

const FAMILY_EMOJI = { call: "☎️", visit: "🏥", message: "📥", condition: "🔍" };
const SUBFAMILY_ARROW = { incoming: "↙️", outgoing: "↗️" };

const GLYPH_BY_KEY = {};
shapeTypesData.families.forEach((fam) => {
  fam.types.forEach((t) => {
    GLYPH_BY_KEY[`${fam.key}::${t.type}`] = t.emoji;
  });
});

function typeEmoji(family, type) {
  return (type && GLYPH_BY_KEY[`${family}::${type}`]) || FAMILY_EMOJI[family];
}

function ShapeGlyphs({ family, type, subfamily }) {
  const mainEmoji = typeEmoji(family, type);
  const familyEmoji = FAMILY_EMOJI[family];
  const showFamilyBadge = familyEmoji && familyEmoji !== mainEmoji;

  return (
    <>
      <span className="pathways-shape-main-emoji">{mainEmoji}</span>
      {showFamilyBadge && (
        <span className="pathways-shape-family-wrap">
          <span className="pathways-shape-family-badge">{familyEmoji}</span>
          {family === "call" && subfamily && (
            <span className="pathways-shape-direction-badge">{SUBFAMILY_ARROW[subfamily] || ""}</span>
          )}
        </span>
      )}
    </>
  );
}

const DRAG_MIME = "application/x-pattern-shape";
const REORDER_MIME = "application/x-pattern-node-id";

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
    // corrupt or unavailable storage — fall back to the seed
  }
  return null;
}

function applyPatternsDoc(json, setPatterns, setSelectedId) {
  if (!Array.isArray(json?.patterns) || !json.patterns.every(isValidPattern)) return;
  setPatterns(json.patterns);
  if (json.selectedId) setSelectedId(json.selectedId);
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

// Some condition nodes stand in for a value that's actually configured
// elsewhere in patterns.json (e.g. "time gap" means "> specialtyRecallDays"),
// not a fixed number. Hovering the shape shows what that resolves to per
// specialty, so it doesn't read as an arbitrary/unexplained rule.
function parameterHint(shape) {
  if (shape.family === "condition" && shape.type === "time gap") {
    const days = patternsSeed.specialtyRecallDays || {};
    const values = Object.entries(days)
      .map(([key, value]) => `${key}: ${value} days`)
      .join(" · ");
    return `Recall interval by specialty — ${values}`;
  }
  return null;
}

function ShapeNode({ node, nodeNumber, onRemove, onDescriptionChange }) {
  const meta = SHAPE_META[node.shape.family];
  const label = node.shape.type || meta.label;
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
        <span className={`pathways-shape ${hint ? "patterns-shape-parameterized" : ""}`} title={title}>
          <ShapeGlyphs family={node.shape.family} type={node.shape.type} subfamily={node.shape.subfamily} />
        </span>
      </div>
      <span className="patterns-node-type-label">{label}</span>
    </div>
  );
}

function SuggestionSlot({ suggestion, onDropShape, onDescriptionChange, onChainLabelChange }) {
  const [over, setOver] = useState(false);
  const shape = suggestion?.shape;
  const label = shape?.type || "Suggestion";

  return (
    <div className="patterns-suggestion-wrap">
      <div
        className={`patterns-suggestion-slot ${over ? "over" : ""}`}
        data-suggestion-slot="true"
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes(DRAG_MIME)) return;
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
          const { family, type, subfamily } = JSON.parse(raw);
          onDropShape(family, type, subfamily);
        }}
      >
        <span className="pathways-node-index">Suggest</span>
        <DescriptionField
          value={suggestion?.description || ""}
          onChange={onDescriptionChange}
        />
        <div className="pathways-shape-wrap">
          <span className="pathways-shape patterns-suggestion-shape" title={label}>
            {shape ? (
              <ShapeGlyphs family={shape.family} type={shape.type} subfamily={shape.subfamily} />
            ) : (
              <span className="pathways-shape-main-emoji">?</span>
            )}
          </span>
        </div>
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
  onSuggestionDrop,
  onSuggestionDescriptionChange,
  onSuggestionChainLabelChange,
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
    if (!isReorder && !e.dataTransfer.types.includes(DRAG_MIME)) return;
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
    if (!raw) {
      setOverIndex(null);
      return;
    }
    const { family, type, subfamily } = JSON.parse(raw);
    onDropShape(family, type, subfamily, indexForPoint(e.clientX));
    setOverIndex(null);
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
            label="Drag call, visit, message or condition shapes here to build the match sequence"
            minHeight="120px"
            className="pathways-canvas-empty"
          />
        ) : (
          <div className="pathways-timeline">
            <div className="pathways-timeline-bg" aria-hidden="true">
              <span className="pathways-node-index" style={{ visibility: "hidden" }}>·</span>
              <span className="pathways-shape-caption above" style={{ visibility: "hidden" }}>·</span>
              <span className="pathways-timeline-bar" />
            </div>
            {pattern.nodes.map((node, i) => (
              <Fragment key={node.id}>
                {overIndex === i && <span className="pathways-drop-marker" />}
                <ShapeNode
                  node={node}
                  nodeNumber={i + 1}
                  onRemove={() => onRemoveNode(node.id)}
                  onDescriptionChange={(value) => onDescriptionChange(node.id, value)}
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
        />
      </div>
    </Card>
  );
}

function ShapeTray() {
  const [family, setFamily] = useState(shapeTypesData.families[0].key);
  const familyDef = shapeTypesData.families.find((f) => f.key === family);

  return (
    <Card padding="lg" className="pathways-tray">
      <div className="pathways-tray-families">
        {shapeTypesData.families.map((f) => (
          <button
            key={f.key}
            type="button"
            className={`pathways-tray-family ${family === f.key ? "on" : ""}`}
            onClick={() => setFamily(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>
      <div className="pathways-tray-types">
        {familyDef.types.map((t) => (
          <div
            key={t.type}
            className="pathways-tray-shape"
            draggable
            tabIndex={0}
            onDragStart={(e) => {
              e.dataTransfer.setData(
                DRAG_MIME,
                JSON.stringify({ family: familyDef.key, type: t.type, subfamily: t.subfamily })
              );
              e.dataTransfer.effectAllowed = "copy";
            }}
          >
            <span className="pathways-shape">
              <ShapeGlyphs family={familyDef.key} type={t.type} subfamily={t.subfamily} />
            </span>
            <span className="pathways-tray-shape-label">{t.type}</span>
            {t.subfamily && <span className="pathways-tray-shape-subfamily">{t.subfamily}</span>}
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function Patterns() {
  const location = useLocation();
  const [initial] = useState(
    () => loadStoredState() ?? { patterns: patternsSeed.patterns, selectedId: patternsSeed.patterns[0].id }
  );
  const [patterns, setPatterns] = useState(initial.patterns);
  // A pattern detected on a patient's timeline wins the initial selection —
  // that's what "Manage suggestions" is opened to look at — over whatever
  // was last selected here.
  const detectedId = location.state?.patternId;
  const startingId =
    detectedId && initial.patterns.some((p) => p.id === detectedId) ? detectedId : initial.selectedId;
  const [selectedId, setSelectedId] = useState(startingId ?? patternsSeed.patterns[0].id);
  const [renamingId, setRenamingId] = useState(null);
  const [saveStatus, setSaveStatus] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/wall/patterns")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((json) => {
        if (cancelled) return;
        applyPatternsDoc(json, setPatterns, setSelectedId);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

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

  const handleDropShape = (family, type, subfamily, index) => {
    setPatterns((prev) =>
      prev.map((p) => {
        if (p.id !== selectedId) return p;
        const nodes = [...p.nodes];
        nodes.splice(index, 0, {
          id: nextId("node"),
          shape: subfamily ? { family, subfamily, type } : { family, type },
          description: "",
        });
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

  const handleSuggestionDrop = (family, type, subfamily) => {
    setPatterns((prev) =>
      prev.map((p) => {
        if (p.id !== selectedId) return p;
        return {
          ...p,
          suggestionNode: {
            ...p.suggestionNode,
            shape: subfamily ? { family, subfamily, type } : { family, type },
            chainLabel: p.suggestionNode?.chainLabel || type,
          },
        };
      })
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
      asOf: patternsSeed.asOf,
      specialtyRecallDays: patternsSeed.specialtyRecallDays,
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
            + Create a new
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
          onSuggestionDrop={handleSuggestionDrop}
          onSuggestionDescriptionChange={handleSuggestionDescription}
          onSuggestionChainLabelChange={handleSuggestionChainLabel}
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
