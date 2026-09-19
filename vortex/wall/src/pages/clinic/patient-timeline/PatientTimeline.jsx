import { Fragment, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import patientTimelines from "../../../data/patientTimelines.json";
import patternsData from "../../../data/patterns.json";
import shapeTypesData from "../../../data/shapeTypes.json";
import { findMatchingPattern } from "../patterns/matchPattern";
import "./patient-timeline.css";

// Not linked from anywhere yet — reachable directly at
// /clinic/patient-timeline/:patientId while this is being built out. Meant
// to eventually open when clicking a call in Live Calls: sort that patient's
// calls/messages/visits by time, filter by specialty, and if they match a
// pattern (see src/data/patterns.json), show the suggested next step ghosted
// at the end of the timeline, plus a separate "why" box explaining the match.

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

// Rejecting a suggestion is permanent for that patient — persisted so it
// never comes back for them. TODO: this is a localStorage stand-in; once a
// real database exists, record the rejection there instead (keyed by
// patient_id + pattern id), the same way pathways/patterns/shapeTypes are
// noted as JSON-only stand-ins elsewhere (see ISSUES.md).
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
function EventNode({ event, isEvidence }) {
  return (
    <div className={`pt-node ${isEvidence ? "pt-node-evidence" : ""}`}>
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
function SuggestionNode({ pattern, onAccept, onReject, status }) {
  const { shape, description } = pattern.suggestionNode;
  return (
    <div className={`pt-node pt-suggestion ${status ? `pt-suggestion-${status}` : ""}`}>
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
function PatternDetectedBox({ pattern }) {
  const count = pattern.nodes.length;
  return (
    <div className="pt-explain">
      <span className="pt-explain-label">Pattern detected</span>
      <div className="pt-pattern-box">
        <div className="pt-pattern-abstract-row">
          {Array.from({ length: count }).map((_, i) => (
            <Fragment key={i}>
              {i > 0 && <span className="pt-pattern-plus">+</span>}
              <span className="pt-pattern-abstract-node" />
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
function TimelineArrow() {
  return (
    <svg className="pt-timeline-arrow" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
      <line x1="0" y1="5" x2="90" y2="5" />
      <path d="M84 1 L94 5 L84 9" fill="none" />
    </svg>
  );
}

export default function PatientTimeline() {
  const { patientId } = useParams();
  const navigate = useNavigate();
  const patient = patientTimelines.patients.find((p) => p.patientId === patientId) || patientTimelines.patients[0];

  // The specialty this history is being read for is always the one the call
  // that opened it was about — never a user-picked filter. There's no
  // per-call specialty on the caller side yet, so it's read off this
  // patient's own most recent specialty-bearing event, which is the closest
  // stand-in for "the specialty of the call" until real call context is
  // threaded through. Events with no specialty at all (general calls,
  // messages or visits) always stay in view alongside it.
  const specialty = useMemo(() => {
    for (let i = patient.events.length - 1; i >= 0; i -= 1) {
      if (patient.events[i].specialty) return patient.events[i].specialty;
    }
    return null;
  }, [patient]);

  const specialtyLabel = specialty ? specialty.charAt(0).toUpperCase() + specialty.slice(1) : null;

  const [suggestionStatus, setSuggestionStatus] = useState(null);
  const [rejectedMap, setRejectedMap] = useState(loadRejectedMap);

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
        patterns: patternsData.patterns,
        specialty,
        asOf: patternsData.asOf,
        specialtyRecallDays: patternsData.specialtyRecallDays,
      }),
    [patient, specialty]
  );

  // A pattern this patient already rejected never comes back for them.
  const rejectedIds = rejectedMap[patient.patientId] || [];
  const match = rawMatch && rejectedIds.includes(rawMatch.pattern.id) ? null : rawMatch;

  const handleReject = () => {
    if (!match) return;
    setRejectedMap((prev) => {
      const next = { ...prev, [patient.patientId]: [...(prev[patient.patientId] || []), match.pattern.id] };
      saveRejectedMap(next);
      return next;
    });
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

  return (
    <div className="pt-page">
      <SectionHeader
        eyebrow="Patient history"
        title={specialtyLabel ? `${patient.name} - ${specialtyLabel}` : patient.name}
        subtitle="Calls, messages and visits, sorted by time."
      />

      {/* Always filtered to this call's own specialty (plus any general,
          specialty-less events) — never a user-picked filter, so no
          selector here. */}
      <div className="pt-main">
        <div className="pt-main-toolbar">
          <Button
            variant="secondary"
            onClick={() => navigate("/clinic/patterns", { state: { patternId: match?.pattern.id } })}
          >
            Manage suggestions
          </Button>
        </div>

        {/* The whole main pane is one white card, its content centered
            vertically as a block. The top row itself is centered as a
            whole; when a pattern matched, the "why" box sits in the same
            column as the suggestion node, right below it, so it reads as
            centered under that dashed shape rather than under the row. */}
        <Card padding="lg" className="pt-main-card">
          <div className="pt-timeline-track">
            {events.map((event) => (
              <EventNode key={event.id} event={event} isEvidence={evidenceIds.has(event.id)} />
            ))}
            {matchedPattern && (
              <Fragment>
                <TimelineArrow />
                <div className="pt-suggestion-column">
                  <SuggestionNode
                    pattern={matchedPattern}
                    status={suggestionStatus}
                    onAccept={() => setSuggestionStatus("accepted")}
                    onReject={handleReject}
                  />
                  <PatternDetectedBox pattern={matchedPattern} />
                </div>
              </Fragment>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
