import { Fragment, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import shapeTypesData from "../../../data/shapeTypes.json";
import { findMatchingPattern } from "../patterns/matchPattern";
import "../live-calls/live-call-detail.css";
import "./patient-timeline.css";

// Not linked from anywhere yet — reachable directly at
// /clinic/patient-timeline/:patientId while this is being built out. Meant
// to eventually open when clicking a call in Live Calls: sort that patient's
// calls/messages/visits by time, filter by specialty, and if they match a
// pattern (GET /api/wall/patterns), show the suggested next step ghosted
// at the end of the timeline, plus a separate "why" box explaining the match.

// What a patient reads as before GET /api/wall/patient-timeline answers,
// and what a patient with no history reads as: their own id and nothing
// else. There is no local pack of example patients any more.
function emptyPatient(patientId) {
  return { patientId, name: patientId, events: [], referrals: [] };
}

//: The patterns document before GET /api/wall/patterns answers. No pattern
//: matches an empty list, so the page simply shows no suggestion until it
//: lands.
const EMPTY_PATTERNS_DOC = { patterns: [], specialtyRecallDays: {} };

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
      <span className="pt-shape-main-emoji">{mainEmoji}</span>
      {showFamilyBadge && (
        <span className="pt-shape-family-wrap">
          <span className="pt-shape-family-badge">{familyEmoji}</span>
          {family === "call" && subfamily && (
            <span className="pt-shape-direction-badge">{SUBFAMILY_ARROW[subfamily] || ""}</span>
          )}
        </span>
      )}
    </>
  );
}

// Rejecting a suggestion is permanent for that patient — the wall API
// stores it keyed by patient_id + pattern id. localStorage is a same-tab
// cache for a board that cannot reach the API.
const REJECTED_KEY = "vortex.rejectedSuggestions.v1";

function loadRejectedMap() {
  try {
    const raw = localStorage.getItem(REJECTED_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveRejectedMap(map) {
  try {
    localStorage.setItem(REJECTED_KEY, JSON.stringify(map));
  } catch {
    // storage unavailable — rejection still holds for this session, just won't persist
  }
}

function formatDate(iso) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// A real, registered event — the only thing the top timeline row ever shows
// (besides the suggestion at its end). `isEvidence` marks it as one of the
// events the detected pattern actually matched on, drawing a highlight box
// around it so the pattern is tied to the concrete facts that triggered it.
function EventNode({ event, isEvidence, gridColumn }) {
  return (
    <div className={`pt-node ${isEvidence ? "pt-node-evidence" : ""}`} style={{ gridColumn }}>
      <span className="pt-node-caption above">{event.description}</span>
      <span className="pt-shape">
        <ShapeGlyphs family={event.shape.family} type={event.shape.type} subfamily={event.shape.subfamily} />
      </span>
      <span className="pt-node-caption below">{formatDate(event.date)}</span>
    </div>
  );
}

// Always full opacity (marked as "not a fact yet" by its dashed border
// alone). Rejecting doesn't show a "dismissed" state here — the whole node
// disappears immediately (see handleReject) — so the only status this ever
// renders is "accepted".
function SuggestionNode({ pattern, onAccept, onReject, status, gridColumn }) {
  const { shape, description } = pattern.suggestionNode;
  return (
    <div className={`pt-node pt-suggestion ${status ? `pt-suggestion-${status}` : ""}`} style={{ gridColumn }}>
      <span className="pt-node-caption above">{description}</span>
      <div className="pt-shape-wrap">
        <span className="pt-shape">
          <ShapeGlyphs family={shape.family} type={shape.type} subfamily={shape.subfamily} />
        </span>
        {!status && (
          <div className="pt-suggestion-actions">
            <button type="button" className="pt-suggestion-btn accept" onClick={onAccept} aria-label="Accept suggestion" title="Accept — schedule outgoing call">
              ✓
            </button>
            <button type="button" className="pt-suggestion-btn reject" onClick={onReject} aria-label="Reject suggestion" title="Reject suggestion — never show it again for this patient">
              ✕
            </button>
          </div>
        )}
      </div>
      <span className="pt-node-caption below pt-suggestion-label">
        {status === "accepted" ? "Scheduled" : "Suggested"}
      </span>
    </div>
  );
}

// The "why": a generic "Pattern detected" label, then a box holding one
// abstract circle per node in the pattern's definition — not the concrete
// events themselves, those are highlighted directly in the timeline row
// above (see EventNode's isEvidence). The pattern's own name is the caption
// underneath, in quotes, naming the shape just drawn. No arrow here — that
// only lives once, in the top row, pointing at the suggestion this box sits
// under.
function PatternDetectedBox({ pattern, gridColumn }) {
  return (
    <div className="pt-explain" style={{ gridColumn }}>
      <span className="pt-explain-label">Pattern detected</span>
      <div className="pt-pattern-box">
        <div className="pt-pattern-abstract-row">
          {pattern.nodes.map((node, i) => (
            <Fragment key={node.id}>
              {i > 0 && <span className="pt-pattern-plus">+</span>}
              <span className="pt-pattern-abstract-node" title={node.shape.type}>
                <ShapeGlyphs family={node.shape.family} type={node.shape.type} subfamily={node.shape.subfamily} />
              </span>
            </Fragment>
          ))}
        </div>
      </div>
      <span className="pt-pattern-name">{`"${pattern.name}"`}</span>
    </div>
  );
}

// Longer than a plain arrow glyph, and reused as the only arrow on the page —
// the pattern box below the suggestion doesn't get its own.
function TimelineArrow({ gridColumn }) {
  return (
    <svg
      className="pt-timeline-arrow"
      viewBox="0 0 100 10"
      preserveAspectRatio="none"
      aria-hidden="true"
      style={{ gridColumn }}
    >
      <line x1="0" y1="5" x2="90" y2="5" />
      <path d="M84 1 L94 5 L84 9" fill="none" />
    </svg>
  );
}

export default function PatientTimeline() {
  const { patientId } = useParams();
  const navigate = useNavigate();
  const [patient, setPatient] = useState(() => emptyPatient(patientId));
  const [patternsDoc, setPatternsDoc] = useState(EMPTY_PATTERNS_DOC);
  const [suggestionStatus, setSuggestionStatus] = useState(null);
  const [rejectedMap, setRejectedMap] = useState(loadRejectedMap);

  useEffect(() => {
    const nextFallback = emptyPatient(patientId);
    setPatient(nextFallback);
    setSuggestionStatus(null);
    let cancelled = false;
    fetch(`/api/wall/patient-timeline/${encodeURIComponent(patientId)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((json) => {
        if (cancelled || !json) return;
        setPatient({
          patientId: json.patientId || patientId,
          name: json.name || nextFallback.name,
          events: Array.isArray(json.events) ? json.events : [],
          referrals: [],
        });
        if (Array.isArray(json.rejectedPatternIds)) {
          setRejectedMap((prev) => ({ ...prev, [patientId]: json.rejectedPatternIds }));
        }
      })
      .catch(() => {
        if (!cancelled) setPatient(nextFallback);
      });
    fetch("/api/wall/patterns")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((json) => {
        if (!cancelled && Array.isArray(json?.patterns)) setPatternsDoc(json);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [patientId]);

  const specialty = useMemo(() => {
    const list = patient.events || [];
    for (let i = list.length - 1; i >= 0; i -= 1) {
      if (list[i].specialty) return list[i].specialty;
    }
    return null;
  }, [patient]);

  const specialtyLabel = specialty ? specialty.charAt(0).toUpperCase() + specialty.slice(1) : null;

  const events = useMemo(
    () => patient.events.filter((e) => !e.specialty || e.specialty === specialty),
    [patient, specialty]
  );

  // Run the same deterministic rules from patterns.json against this
  // patient's own events — nothing about the match is hardcoded per patient.
  const rawMatch = useMemo(
    () =>
      findMatchingPattern({
        events: patient.events,
        referrals: patient.referrals || [],
        patterns: patternsDoc.patterns || [],
        specialty,
        asOf: patternsDoc.asOf,
        specialtyRecallDays: patternsDoc.specialtyRecallDays,
      }),
    [patient, specialty, patternsDoc]
  );

  // A pattern this patient already rejected never comes back for them.
  const rejectedIds = rejectedMap[patient.patientId] || [];
  const match = rawMatch && rejectedIds.includes(rawMatch.pattern.id) ? null : rawMatch;

  const handleReject = () => {
    if (!match || patient.patientId !== patientId) return;
    const patternId = match.pattern.id;
    setRejectedMap((prev) => {
      const next = { ...prev, [patient.patientId]: [...(prev[patient.patientId] || []), patternId] };
      saveRejectedMap(next);
      return next;
    });
    fetch(`/api/wall/patient-timeline/${encodeURIComponent(patient.patientId)}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patternId }),
    }).catch(() => {});
  };

  // Suggestion copy is generic ("<specialty>") — fill in the real specialty
  // this patient's history actually matched on for display.
  const matchedPattern = match && {
    ...match.pattern,
    suggestionNode: {
      ...match.pattern.suggestionNode,
      description: (match.pattern.suggestionNode?.description || "").replace(
        /<specialty>/gi,
        match.specialty || "this specialty"
      ),
    },
  };

  const evidenceIds = new Set(match ? match.evidenceEventIds : []);

  // The "why" box sits centered under the evidence event(s) it explains —
  // spanning from the first to the last evidence column when a pattern
  // touched more than one real event — never under the suggestion. A
  // pattern with no real-event evidence (condition-only rules, e.g. an
  // unfulfilled referral) has nothing to point at, so it falls back to the
  // suggestion's own column.
  const evidenceColumns = events.reduce((acc, event, i) => {
    if (evidenceIds.has(event.id)) acc.push(i + 1);
    return acc;
  }, []);
  const explainGridColumn = evidenceColumns.length
    ? `${evidenceColumns[0]} / ${evidenceColumns[evidenceColumns.length - 1] + 1}`
    : `${events.length + 2}`;

  return (
    <div className="transcript-page">
      {/* Same shell as the Live Call detail page (transcript-card, tx-head,
          tx-close) — this opens over whatever page linked here the same
          way a call opens from Home, and the × returns there via
          navigate(-1) rather than a hardcoded destination. */}
      <Card padding="sm" className="transcript-card">
        <header className="tx-head">
          <div className="tx-head-left">
            <div className="tx-head-copy">
              <h1>{specialtyLabel ? `${patient.name} - ${specialtyLabel}` : patient.name}</h1>
              <p>Calls, messages and visits, sorted by time.</p>
            </div>
          </div>
          <div className="tx-head-actions">
            <Button
              variant="secondary"
              onClick={() => navigate("/clinic/patterns", { state: { patternId: match?.pattern.id } })}
            >
              Manage suggestions
            </Button>
            <button type="button" className="tx-close" aria-label="Close" onClick={() => navigate(-1)}>
              ×
            </button>
          </div>
        </header>

        {/* Always filtered to this call's own specialty (plus any general,
            specialty-less events) — never a user-picked filter, so no
            selector here. */}
        <div className="pt-body">
          {/* A CSS grid (not flex), centered as a block, so the "why" box
              below can be placed by column index, centered under the
              evidence node(s) it explains instead of under the suggestion. */}
          <div className="pt-timeline-track">
            {events.map((event, i) => (
              <EventNode
                key={event.id}
                event={event}
                isEvidence={evidenceIds.has(event.id)}
                gridColumn={i + 1}
              />
            ))}
            {matchedPattern && (
              <Fragment>
                <TimelineArrow gridColumn={events.length + 1} />
                <SuggestionNode
                  pattern={matchedPattern}
                  status={suggestionStatus}
                  onAccept={() => setSuggestionStatus("accepted")}
                  onReject={handleReject}
                  gridColumn={events.length + 2}
                />
                <PatternDetectedBox pattern={matchedPattern} gridColumn={explainGridColumn} />
              </Fragment>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
