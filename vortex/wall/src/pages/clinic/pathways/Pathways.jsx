import { useRef, useState, useEffect, useId, Fragment } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import Placeholder from "../../../components/ui/Placeholder";
import pathwaysSeed from "../../../data/pathways.json";
import shapeTypesData from "../../../data/shapeTypes.json";
import "./pathways.css";

// Reached from the Sidebar via the "Pathways & Patterns" toggle page
// (patterns-pathways/PatternsPathways.jsx); also reachable directly at
// /clinic/pathways for testing this editor on its own. See AppRouter.jsx.
//
// Seeded from src/data/pathways.json and src/data/shapeTypes.json — flat
// JSON stand-ins for a real store for now (see those files' _comment).
// Swapping them for a fetch to a backend endpoint later only touches the
// two seed imports below.

const SHAPE_META = {
  call: { label: "Call" },
  message: { label: "Message" },
  visit: { label: "Visit" },
  condition: { label: "Condition" },
  entry: { label: "Entry point" },
};

// The entry point is every pathway's fixed first node — the trigger that
// starts it. It isn't one of the draggable shape/type combos in
// shapeTypes.json: it always renders the same bell glyph and has no `when`
// (there's nothing before it to time itself against), so it's its own
// family rather than a family+type pair from the catalog.
const ENTRY_EMOJI = "🛎️";
function isEntryNode(node) {
  return node.shape.family === "entry";
}

// The main bubble shows the exact type's emoji. Calls additionally get a
// small direction arrow badge pinned to the family emoji's own corner
// (bottom-right of the shape) — every call is an outgoing action we take,
// so the arrow is unconditional now, not tied to a subfamily. Every node
// gets that bare family emoji (call/message/visit/condition) there too,
// unless it's identical to the main one. "condition" only shows up when
// building a pattern (see pages/clinic/patterns) — it has no place in a
// real pathway, but lives in the same shared catalog.
const FAMILY_EMOJI = { call: "☎️", visit: "🏥", message: "📥", condition: "🔍" };
const CALL_DIRECTION_ARROW = "↗️";

const GLYPH_BY_KEY = {};
const DEFAULT_WHEN_BY_KEY = {};
shapeTypesData.families.forEach((fam) => {
  fam.types.forEach((t) => {
    GLYPH_BY_KEY[`${fam.key}::${t.type}`] = t.emoji;
    DEFAULT_WHEN_BY_KEY[`${fam.key}::${t.type}`] = t.defaultWhen;
  });
});

function typeEmoji(family, type) {
  return (type && GLYPH_BY_KEY[`${family}::${type}`]) || FAMILY_EMOJI[family];
}

// Renders the main type emoji plus, unless it's a duplicate, the bare
// family emoji with the call direction arrow pinned to its own corner.
function ShapeGlyphs({ family, type }) {
  const mainEmoji = typeEmoji(family, type);
  const familyEmoji = FAMILY_EMOJI[family];
  const showFamilyBadge = familyEmoji && familyEmoji !== mainEmoji;

  return (
    <>
      <span className="pathways-shape-main-emoji">{mainEmoji}</span>
      {showFamilyBadge && (
        <span className="pathways-shape-family-wrap">
          <span className="pathways-shape-family-badge">{familyEmoji}</span>
          {family === "call" && (
            <span className="pathways-shape-direction-badge">{CALL_DIRECTION_ARROW}</span>
          )}
        </span>
      )}
    </>
  );
}

const DRAG_MIME = "application/x-pathway-shape";
const REORDER_MIME = "application/x-pathway-node-id";

// Manual save only (via the header's save button) — not on every keystroke.
// Flat localStorage stand-in for a real store for now, same spirit as the
// two JSON seeds this page reads from.
const STORAGE_KEY = "vortex.pathways.v1";

// The shapes catalog used to store a call's type as one combined string
// ("incoming - scheduling"), then as a separate subfamily/type pair, before
// dropping the incoming/outgoing distinction entirely — calls are always
// outgoing actions now. A browser that saved under either older shape has
// call nodes sitting in localStorage — this brings them forward to the
// current (subfamily-less) schema every time stored state loads.
const CALL_TYPE_RENAMES = { "new appointment suggestion": "appointment suggestion" };

function migrateCallShape(shape) {
  if (!shape || shape.family !== "call") return shape;
  if (typeof shape.type === "string") {
    const match = shape.type.match(/^(incoming|outgoing)\s*-\s*(.+)$/i);
    if (match) {
      const [, , rest] = match;
      return { family: "call", type: CALL_TYPE_RENAMES[rest] || rest };
    }
  }
  if (shape.subfamily) {
    const { subfamily: _subfamily, ...rest } = shape;
    return rest;
  }
  return shape;
}

// A pathway's first node used to be a regular call/visit shape playing
// double duty as the trigger. It's now its own "entry" family — this brings
// stored pathways from before that change forward.
function migrateEntryNode(nodes) {
  if (nodes.length === 0 || nodes[0].shape.family === "entry") return nodes;
  const [first, ...rest] = nodes;
  return [{ ...first, shape: { family: "entry" }, when: null }, ...rest];
}

function migratePathways(pathways) {
  return pathways.map((w) => ({
    ...w,
    nodes: migrateEntryNode(w.nodes.map((n) => ({ ...n, shape: migrateCallShape(n.shape) }))),
  }));
}

function loadStoredState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed.pathways) && parsed.pathways.length > 0) {
      return { ...parsed, pathways: migratePathways(parsed.pathways) };
    }
  } catch {
    // corrupt or unavailable storage — fall back to the seed
  }
  return null;
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

const WHEN_KIND_OPTIONS = [
  { value: "asap", label: "ASAP" },
  { value: "when_scheduled", label: "When scheduled" },
  { value: "proactive", label: "Proactively triggered" },
];

const AMOUNT_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 21, 30, 45, 60, 90, 180, 270, 340, 365];
const UNIT_OPTIONS = ["hours", "days", "months"];
const DIRECTION_OPTIONS = ["after", "before"];

let uid = 0;
const nextId = (prefix) => `${prefix}-${(uid += 1)}`;

function makePathway(name) {
  return {
    id: nextId("wf"),
    name,
    description: "",
    nodes: [
      {
        id: nextId("node"),
        shape: { family: "entry" },
        when: null,
        description: "Client requesting appointment",
      },
    ],
  };
}

// A brand-new node's default `when`: the type's own default, or ASAP when
// that default is "proactive" but there's no earlier node to time it from.
function defaultWhenForDrop(family, type, index) {
  const kind = DEFAULT_WHEN_BY_KEY[`${family}::${type}`] || "asap";
  if (kind === "proactive") {
    if (index === 0) return { kind: "asap" };
    return { kind: "proactive", amount: 1, unit: "days", direction: "after", referenceNode: index };
  }
  return { kind };
}

// A small text field with datalist autocomplete, constrained to `options`:
// on blur/Enter it snaps to the matching option (by its displayed or raw
// form) or reverts to the last valid value — it can never commit anything
// outside the allowed set.
function ConstrainedField({ value, options, format = String, onCommit }) {
  const listId = useId();
  const [text, setText] = useState(format(value));

  useEffect(() => {
    setText(format(value));
  }, [value]);

  const commit = () => {
    const query = text.trim().toLowerCase();
    const match = options.find(
      (o) => format(o).toLowerCase() === query || String(o).toLowerCase() === query
    );
    if (match !== undefined) {
      onCommit(match);
      setText(format(match));
    } else {
      setText(format(value));
    }
  };

  return (
    <>
      <input
        type="text"
        className="pathways-when-field"
        list={listId}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") setText(format(value));
        }}
      />
      <datalist id={listId}>
        {options.map((o) => (
          <option key={format(o)} value={format(o)} />
        ))}
      </datalist>
    </>
  );
}

function WhenEditor({ node, nodeNumber, totalNodes, onKindChange, onFieldChange }) {
  const when = node.when || { kind: "asap" };
  const nodeOptions = [];
  for (let n = 1; n <= totalNodes; n += 1) {
    if (n !== nodeNumber) nodeOptions.push(n);
  }

  return (
    <div className="pathways-when">
      <select
        className="ui-select pathways-when-kind"
        value={when.kind}
        onChange={(e) => onKindChange(e.target.value)}
      >
        {WHEN_KIND_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>

      {when.kind === "proactive" && (
        <>
          <div className="pathways-when-row">
            <ConstrainedField
              value={when.amount ?? 1}
              options={AMOUNT_OPTIONS}
              onCommit={(v) => onFieldChange("amount", v)}
            />
            <ConstrainedField
              value={when.unit ?? "days"}
              options={UNIT_OPTIONS}
              onCommit={(v) => onFieldChange("unit", v)}
            />
          </div>
          <div className="pathways-when-row">
            <ConstrainedField
              value={when.direction ?? "after"}
              options={DIRECTION_OPTIONS}
              onCommit={(v) => onFieldChange("direction", v)}
            />
            <ConstrainedField
              value={when.referenceNode ?? nodeOptions[0]}
              options={nodeOptions}
              format={(n) => `node${n}`}
              onCommit={(v) => onFieldChange("referenceNode", v)}
            />
          </div>
        </>
      )}
    </div>
  );
}

// Plain text until clicked — no input chrome, no placeholder. A click swaps
// it for a text field; blur/Enter commits, Escape cancels. `entry` renders
// the display text bigger, quoted and upper-cased — the entry point's
// description reads as the line the caller actually said, not a caption —
// while keeping the same box height so its icon still lines up with every
// other node's.
function DescriptionField({ value, onChange, entry }) {
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <input
        type="text"
        className={`pathways-description-input ${entry ? "pathways-description-input-entry" : ""}`}
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
      className={`pathways-shape-caption above pathways-description-display ${entry ? "pathways-description-entry" : ""}`}
      role="button"
      tabIndex={0}
      onClick={() => setEditing(true)}
      onKeyDown={(e) => {
        if (e.key === "Enter") setEditing(true);
      }}
    >
      {entry ? `"${value}"` : value}
    </span>
  );
}

function ShapeNode({ node, nodeNumber, totalNodes, onRemove, onWhenKindChange, onWhenFieldChange, onDescriptionChange }) {
  const isEntry = isEntryNode(node);
  const meta = SHAPE_META[node.shape.family];
  const label = isEntry ? meta.label : node.shape.type || meta.label;

  return (
    <div
      className="pathways-shape-node"
      data-step="true"
      draggable={!isEntry}
      onDragStart={
        isEntry
          ? undefined
          : (e) => {
              e.dataTransfer.setData(REORDER_MIME, node.id);
              e.dataTransfer.effectAllowed = "move";
            }
      }
    >
      {/* A non-breaking space, not an empty string, for the entry point: it keeps
          this label's line box the same height as a real "Node N" one so the
          icon row below still lines up, without showing "Node 1" on screen. */}
      <span className="pathways-node-index" aria-hidden={isEntry || undefined}>
        {isEntry ? " " : `Node ${nodeNumber}`}
      </span>
      <DescriptionField value={node.description} onChange={onDescriptionChange} entry={isEntry} />
      <div className="pathways-shape-wrap">
        {!isEntry && (
          <button
            type="button"
            className="pathways-shape-remove"
            onClick={onRemove}
            aria-label={`Remove ${label} step`}
          >
            ×
          </button>
        )}
        {isEntry ? (
          <span className="pathways-shape pathways-shape-entry" title={label}>
            <span className="pathways-shape-main-emoji">{ENTRY_EMOJI}</span>
          </span>
        ) : (
          <span className="pathways-shape" title={label}>
            <ShapeGlyphs family={node.shape.family} type={node.shape.type} />
          </span>
        )}
      </div>
      {isEntry ? (
        <div className="pathways-when pathways-when-entry">
          <span className="pathways-entry-label">Entry point</span>
        </div>
      ) : (
        <WhenEditor
          node={node}
          nodeNumber={nodeNumber}
          totalNodes={totalNodes}
          onKindChange={onWhenKindChange}
          onFieldChange={onWhenFieldChange}
        />
      )}
    </div>
  );
}

function PathwayCanvas({
  pathway,
  onDropShape,
  onReorderNode,
  onRemoveNode,
  onWhenKindChange,
  onWhenFieldChange,
  onDescriptionChange,
}) {
  const trackRef = useRef(null);
  const [overIndex, setOverIndex] = useState(null);

  const indexForPoint = (clientX) => {
    const track = trackRef.current;
    if (!track) return pathway.nodes.length;
    const items = Array.from(track.querySelectorAll("[data-step]"));
    for (let i = 0; i < items.length; i += 1) {
      const rect = items[i].getBoundingClientRect();
      if (clientX < rect.left + rect.width / 2) return i;
    }
    return items.length;
  };

  const handleDragOver = (e) => {
    const isReorder = e.dataTransfer.types.includes(REORDER_MIME);
    if (!isReorder && !e.dataTransfer.types.includes(DRAG_MIME)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = isReorder ? "move" : "copy";
    setOverIndex(indexForPoint(e.clientX));
  };

  const handleDrop = (e) => {
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
    const { family, type } = JSON.parse(raw);
    onDropShape(family, type, indexForPoint(e.clientX));
    setOverIndex(null);
  };

  return (
    <Card padding="lg" className="pathways-canvas">
      <div
        className={`pathways-canvas-track ${overIndex != null ? "over" : ""}`}
        ref={trackRef}
        onDragOver={handleDragOver}
        onDragLeave={() => setOverIndex(null)}
        onDrop={handleDrop}
      >
        {pathway.nodes.length === 0 ? (
          <Placeholder
            kind="diagram"
            label="Drag a call, message or visit shape here to start this pathway"
            minHeight="120px"
            className="pathways-canvas-empty"
          />
        ) : (
          <div className="pathways-timeline">
            <div className="pathways-timeline-bg" aria-hidden="true">
              <span className="pathways-node-index" style={{ visibility: "hidden" }}>·</span>
              <span className="pathways-shape-caption above" style={{ visibility: "hidden" }}>·</span>
              <div className="pathways-timeline-bars">
                {pathway.nodes.map((node) => (
                  <span key={node.id} className="pathways-timeline-bar" />
                ))}
              </div>
            </div>
            {pathway.nodes.map((node, i) => (
              <Fragment key={node.id}>
                {overIndex === i && <span className="pathways-drop-marker" />}
                <ShapeNode
                  node={node}
                  nodeNumber={i + 1}
                  totalNodes={pathway.nodes.length}
                  onRemove={() => onRemoveNode(node.id)}
                  onWhenKindChange={(kind) => onWhenKindChange(node.id, kind, i)}
                  onWhenFieldChange={(field, value) => onWhenFieldChange(node.id, field, value)}
                  onDescriptionChange={(value) => onDescriptionChange(node.id, value)}
                />
              </Fragment>
            ))}
            {overIndex === pathway.nodes.length && (
              <span className="pathways-drop-marker" />
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

function ShapeTray() {
  // "condition" is pattern-building only — keep it out of real pathways.
  const trayFamilies = shapeTypesData.families.filter((f) => f.key !== "condition");
  const [family, setFamily] = useState(trayFamilies[0].key);
  const familyDef = trayFamilies.find((f) => f.key === family);

  return (
    <Card padding="lg" className="pathways-tray">
      <div className="pathways-tray-families">
        {trayFamilies.map((f) => (
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
              e.dataTransfer.setData(DRAG_MIME, JSON.stringify({ family: familyDef.key, type: t.type }));
              e.dataTransfer.effectAllowed = "copy";
            }}
          >
            <span className="pathways-shape">
              <ShapeGlyphs family={familyDef.key} type={t.type} />
            </span>
            <span className="pathways-tray-shape-label">{t.type}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function Pathways() {
  const [initial] = useState(
    () => loadStoredState() ?? { pathways: pathwaysSeed.pathways, selectedId: pathwaysSeed.pathways[0].id }
  );
  const [pathways, setPathways] = useState(initial.pathways);
  const [selectedId, setSelectedId] = useState(initial.selectedId);
  const [renamingId, setRenamingId] = useState(null);
  const [saveStatus, setSaveStatus] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const selected = pathways.find((w) => w.id === selectedId) ?? pathways[0];

  const handleCreate = () => {
    const wf = makePathway("Untitled pathway");
    setPathways((prev) => [...prev, wf]);
    setSelectedId(wf.id);
    setRenamingId(wf.id);
  };

  const handleDeletePathway = () => {
    const index = pathways.findIndex((w) => w.id === selectedId);
    const next = pathways.filter((w) => w.id !== selectedId);
    setPathways(next);
    const fallback = next[Math.max(0, index - 1)] ?? next[0];
    if (fallback) setSelectedId(fallback.id);
    setShowDeleteConfirm(false);
  };

  const commitRename = (id, rawName) => {
    const name = rawName.trim();
    setPathways((prev) => prev.map((w) => (w.id === id ? { ...w, name: name || "Untitled pathway" } : w)));
    setRenamingId(null);
  };

  const handleDropShape = (family, type, rawIndex) => {
    setPathways((prev) =>
      prev.map((w) => {
        if (w.id !== selectedId) return w;
        // Node 0 is always the entry point — nothing can be dropped in front of it.
        const index = Math.max(rawIndex, 1);
        const nodes = [...w.nodes];
        nodes.splice(index, 0, {
          id: nextId("node"),
          shape: { family, type },
          when: defaultWhenForDrop(family, type, index),
          description: "",
        });
        return { ...w, nodes };
      })
    );
  };

  const handleWhenKindChange = (nodeId, kind, index) => {
    setPathways((prev) =>
      prev.map((w) => {
        if (w.id !== selectedId) return w;
        const nodes = w.nodes.map((n) => {
          if (n.id !== nodeId) return n;
          if (kind === "proactive") {
            return {
              ...n,
              when: {
                kind,
                amount: n.when?.amount ?? 1,
                unit: n.when?.unit ?? "days",
                direction: n.when?.direction ?? "after",
                referenceNode: n.when?.referenceNode ?? (index > 0 ? index : 2),
              },
            };
          }
          return { ...n, when: { kind } };
        });
        return { ...w, nodes };
      })
    );
  };

  const handleWhenFieldChange = (nodeId, field, value) => {
    setPathways((prev) =>
      prev.map((w) => {
        if (w.id !== selectedId) return w;
        const nodes = w.nodes.map((n) => (n.id === nodeId ? { ...n, when: { ...n.when, [field]: value } } : n));
        return { ...w, nodes };
      })
    );
  };

  const handleReorderNode = (nodeId, dropIndex) => {
    setPathways((prev) =>
      prev.map((w) => {
        if (w.id !== selectedId) return w;
        const nodes = [...w.nodes];
        const fromIndex = nodes.findIndex((n) => n.id === nodeId);
        // The entry point can't be reordered, and nothing can be dropped in front of it.
        if (fromIndex <= 0 || isEntryNode(nodes[fromIndex])) return w;
        const [moved] = nodes.splice(fromIndex, 1);
        const insertAt = Math.max(fromIndex < dropIndex ? dropIndex - 1 : dropIndex, 1);
        nodes.splice(insertAt, 0, moved);
        return { ...w, nodes };
      })
    );
  };

  const handleRemoveNode = (nodeId) => {
    setPathways((prev) =>
      prev.map((w) =>
        // The entry point can't be removed — a pathway always needs its trigger.
        w.id === selectedId ? { ...w, nodes: w.nodes.filter((n) => n.id !== nodeId || isEntryNode(n)) } : w
      )
    );
  };

  const handleUpdateDescription = (nodeId, description) => {
    setPathways((prev) =>
      prev.map((w) => {
        if (w.id !== selectedId) return w;
        const nodes = w.nodes.map((n) => (n.id === nodeId ? { ...n, description } : n));
        return { ...w, nodes };
      })
    );
  };

  const handleSave = () => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ pathways, selectedId }));
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus(null), 2000);
    } catch {
      // storage unavailable — in-memory state still works, just won't persist
    }
  };

  return (
    <div className="pathways-page">
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
              {pathways.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          )}
          <button
            type="button"
            className="pathways-rename-btn"
            onClick={() => setRenamingId(selectedId)}
            aria-label="Rename pathway"
            title="Rename pathway"
          >
            ✎
          </button>
          <button
            type="button"
            className="pathways-delete-btn"
            onClick={() => setShowDeleteConfirm(true)}
            disabled={pathways.length <= 1}
            aria-label="Delete pathway"
            title={pathways.length <= 1 ? "Can't delete the only pathway" : "Delete pathway"}
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
            + Create a new pathway
          </Button>
        </div>
      </div>

      <div className="pathways-main">
        <PathwayCanvas
          pathway={selected}
          onDropShape={handleDropShape}
          onReorderNode={handleReorderNode}
          onRemoveNode={handleRemoveNode}
          onWhenKindChange={handleWhenKindChange}
          onWhenFieldChange={handleWhenFieldChange}
          onDescriptionChange={handleUpdateDescription}
        />
        <ShapeTray />
      </div>

      {showDeleteConfirm && (
        <div className="ui-modal-overlay" onClick={() => setShowDeleteConfirm(false)}>
          <div className="ui-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ui-modal-head">
              <h3>Delete pathway</h3>
              <button className="ui-modal-close" onClick={() => setShowDeleteConfirm(false)}>✕</button>
            </div>
            <div className="ui-modal-body">
              <p>Delete “{selected.name}”? This can't be undone.</p>
            </div>
            <div className="ui-modal-actions">
              <Button variant="ghost" onClick={() => setShowDeleteConfirm(false)}>Cancel</Button>
              <Button variant="primary" onClick={handleDeletePathway}>Delete</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
