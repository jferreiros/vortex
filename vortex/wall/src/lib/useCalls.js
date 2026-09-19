import { useEffect, useRef, useState } from "react";
import { mockCallsStream } from "./mockCalls";

// Data source for the Calls table. The line server answers GET /calls with
// the call events grouped by call_id ({ calls: { id: [events...] }, meta });
// a board that proxies it exposes the same payload under /api/wall/calls.
// Both are tried because which one exists depends on the deployment; when
// neither answers with the grouped shape the hook falls back to the scripted
// demo list so the page still works with no backend (mockTimeline pattern).
const POLL_MS = 1500;
const CALLS_LIMIT = 50;
const SOURCES = ["/api/wall/calls", "/calls"];

// A call with no event for this long is over, whatever the log says — the
// same rule the board applies (vortex/observability/live.py STALE_AFTER_S).
const STALE_AFTER_MS = 180_000;

// Mirrors view.py's CallCard.status: the submitted action kind names the
// outcome; an ended call with no action is just "ended".
const ACTION_TO_STATUS = {
  book: "booked",
  register: "registered",
  reschedule: "rescheduled",
  cancel: "cancelled",
  escalate: "escalated",
  "no-action": "refused",
};

// "+34 612 345 678" -> "+34 6•••••678". Public pages never show a full
// number — a JS port of insights.mask_phone so the table masks callers the
// same way the NiceGUI wall does.
export function maskPhone(value) {
  if (!value) return "—";
  const text = String(value);
  const digits = [...text].filter((ch) => ch >= "0" && ch <= "9");
  if (digits.length < 6) return "•".repeat(text.length);
  const head = text.startsWith("+") ? text.slice(0, 4) : text.slice(0, 1);
  const tail = digits.slice(-3).join("");
  const hidden = Math.max(digits.length - head.replace("+", "").length - 3, 3);
  return `${head}${"•".repeat(hidden)}${tail}`;
}

function toMs(value) {
  const t = value ? Date.parse(value) : NaN;
  return Number.isNaN(t) ? null : t;
}

function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function asObj(value) {
  return value && typeof value === "object" ? value : {};
}

// "/api/v1/submit/book" -> "book". The submit route tail is the action kind.
function actionKindFromRoute(route) {
  if (typeof route !== "string" || !route) return null;
  const tail = route.replace(/\/+$/, "").split("/").pop();
  return tail || null;
}

// find_patient results carry patient.full_name on the mock lane and the
// EHR's given/first/second surname split on the real one — take whichever
// is there, same precedence as view.py's _patient_name.
function patientNameFrom(result) {
  const patient = asObj(result).patient;
  if (!patient || typeof patient !== "object") return null;
  if (patient.full_name) return String(patient.full_name);
  const parts = [patient.given_name, patient.first_surname, patient.second_surname].filter(Boolean);
  return parts.length ? parts.join(" ") : null;
}

function patientIdFrom(result) {
  const patient = asObj(result).patient;
  return patient && patient.patient_id ? String(patient.patient_id) : null;
}

function declineFrom(result) {
  const data = asObj(result);
  const rejection = data.rejection;
  if (rejection && typeof rejection === "object" && rejection.reason) return String(rejection.reason);
  if (data.reason && (data.kind === "no-action" || data.kind === "escalate")) return String(data.reason);
  return null;
}

function actionFrom(result) {
  const data = asObj(result);
  if (data.action && typeof data.action === "object" && data.action.kind) return String(data.action.kind);
  if (data.kind) return String(data.kind);
  return null;
}

// Replay one call's chronological events into the row the table draws —
// the JS twin of view.build_call + wall_timeline.call_summary, plus the
// fields only the table needs (live phase for the wave strip, the
// call.recording event the data layer writes once the WAV lands).
export function deriveCall(callId, events, now = Date.now()) {
  const call = {
    callId,
    startedAt: null,
    startedMs: null,
    endedAt: null,
    lastTs: null,
    fromNumber: null,
    fromMasked: "—",
    voice: null,
    clinic: null,
    patientName: null,
    patientId: null,
    intent: null,
    language: null,
    actionKind: null,
    submitStatus: null,
    declineReason: null,
    endReason: null,
    durationMs: null,
    recording: null,
    ended: false,
    live: true,
    status: "live",
    phase: "connecting",
  };
  const openTools = [];
  let lastKind = null;
  let sawStarted = false;

  for (const ev of events || []) {
    const kind = ev?.kind;
    if (!kind) continue;
    if (ev.ts) call.lastTs = ev.ts;
    lastKind = kind;

    switch (kind) {
      case "call.started":
        sawStarted = true;
        call.startedAt = ev.ts || ev.connected_at || null;
        call.fromNumber = ev.from_number || null;
        call.voice = ev.voice || null;
        call.clinic = ev.clinic || null;
        break;
      case "tool.called":
        openTools.push(String(ev.tool || "?"));
        break;
      case "tool.returned":
      case "tool.failed": {
        const name = String(ev.tool || "?");
        const idx = openTools.lastIndexOf(name);
        if (idx >= 0) openTools.splice(idx, 1);
        if (kind === "tool.returned") {
          const result = ev.result;
          const nameGuess = patientNameFrom(result);
          if (nameGuess) call.patientName = nameGuess;
          const idGuess = patientIdFrom(result);
          if (idGuess) call.patientId = idGuess;
          const declineGuess = declineFrom(result);
          if (declineGuess) call.declineReason = declineGuess;
          const actionGuess = actionFrom(result);
          if (actionGuess) call.actionKind = actionGuess;
        }
        break;
      }
      case "submit.sent":
      case "submit.result": {
        const kindGuess = actionKindFromRoute(ev.route);
        if (kindGuess) call.actionKind = kindGuess;
        const result = ev.result;
        if (result && typeof result === "object" && result.status) {
          call.submitStatus = String(result.status);
        } else if (typeof result === "string" && result) {
          call.submitStatus = result;
        }
        const payload = ev.payload;
        if (payload && typeof payload === "object" && payload.reason) {
          call.declineReason = String(payload.reason);
        }
        break;
      }
      case "call.intent": {
        const value = String(ev.intent || "").trim();
        if (value) call.intent = value;
        break;
      }
      case "voice.language_switch":
        call.language = ev.now || call.language;
        break;
      case "call.recording":
        // Emitted by the line on call.ended when a WAV was written
        // (docs/product-control-center.md data layer spec).
        call.recording = {
          path: ev.path || null,
          format: ev.format || "wav",
          durationMs: num(ev.duration_ms),
          bytes: num(ev.bytes),
        };
        break;
      case "call.ended":
        call.ended = true;
        call.endedAt = ev.ts || call.endedAt;
        call.endReason = ev.reason || call.endReason;
        break;
      case "call.crashed":
        call.ended = true;
        call.endedAt = ev.ts || call.endedAt;
        call.endReason = ev.reason || "crashed";
        break;
      case "call.summary": {
        call.ended = true;
        call.endedAt = ev.ts || call.endedAt;
        const duration = num(ev.duration_ms);
        if (duration != null) call.durationMs = duration;
        if (ev.reason) call.endReason = String(ev.reason);
        const actions = Array.isArray(ev.actions) ? ev.actions : [];
        const last = actions[actions.length - 1];
        if (last && typeof last === "object") {
          const kindGuess = actionKindFromRoute(last.route);
          if (kindGuess) call.actionKind = kindGuess;
          if (last.payload && typeof last.payload === "object" && last.payload.reason) {
            call.declineReason = String(last.payload.reason);
          }
        }
        break;
      }
      default:
        break;
    }
  }

  call.fromMasked = maskPhone(call.fromNumber);
  call.startedMs = toMs(call.startedAt) ?? toMs(call.lastTs);
  const lastMs = toMs(call.lastTs);
  if (!call.ended && lastMs != null && now - lastMs > STALE_AFTER_MS) {
    call.ended = true;
    call.endReason = call.endReason || "stale";
  }
  call.live = !call.ended;
  call.status = call.ended ? ACTION_TO_STATUS[call.actionKind] || "ended" : "live";
  // An ended call with no call.summary still gets a duration: last event
  // minus the connect, same fallback as live.py's _duration.
  if (call.ended && call.durationMs == null && call.startedMs != null && lastMs != null) {
    call.durationMs = Math.max(0, lastMs - call.startedMs);
  }
  call.phase = call.ended
    ? "ended"
    : openTools.length
      ? "working"
      : lastKind === "turn.assistant"
        ? "speaking"
        : lastKind === "turn.user"
          ? "thinking"
          : sawStarted
            ? "listening"
            : "connecting";
  return call;
}

function validGrouped(data) {
  return (
    data &&
    typeof data === "object" &&
    data.calls &&
    typeof data.calls === "object" &&
    !Array.isArray(data.calls)
  );
}

async function fetchGrouped(url) {
  try {
    const res = await fetch(`${url}?calls=${CALLS_LIMIT}`);
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    return validGrouped(data) ? data.calls : null;
  } catch {
    return null;
  }
}

// Polls the calls source and returns { calls, demo, failed }: the derived
// rows newest-first, whether the demo stream is what's on screen, and
// whether the last poll dropped (in which case the previous rows stay).
export function useCalls() {
  const [state, setState] = useState({ calls: [], demo: false, failed: false });
  const cancelledRef = useRef(false);
  const sourceRef = useRef(null);
  const hadDataRef = useRef(false);
  const mockStopRef = useRef(null);

  useEffect(() => {
    cancelledRef.current = false;
    sourceRef.current = null;
    hadDataRef.current = false;

    const stopMock = () => {
      mockStopRef.current?.();
      mockStopRef.current = null;
    };
    const startMock = () => {
      if (mockStopRef.current) return;
      mockStopRef.current = mockCallsStream((calls) => {
        if (!cancelledRef.current) setState({ calls, demo: true, failed: false });
      });
    };

    async function poll() {
      // The source that worked last time goes first so a resolved endpoint
      // costs one request per tick; a miss re-tries the other candidate.
      const order = sourceRef.current
        ? [sourceRef.current, ...SOURCES.filter((u) => u !== sourceRef.current)]
        : SOURCES;
      let grouped = null;
      let used = null;
      for (const url of order) {
        grouped = await fetchGrouped(url);
        if (grouped) {
          used = url;
          break;
        }
      }
      if (cancelledRef.current) return;

      if (grouped) {
        sourceRef.current = used;
        hadDataRef.current = true;
        stopMock();
        const now = Date.now();
        const calls = Object.entries(grouped)
          .map(([callId, events]) => deriveCall(callId, Array.isArray(events) ? events : [], now))
          .sort((a, b) => (b.startedMs ?? 0) - (a.startedMs ?? 0));
        setState({ calls, demo: false, failed: false });
      } else {
        sourceRef.current = null;
        if (hadDataRef.current) {
          // Keep the last good rows: a dropped poll degrades to slightly
          // stale real data plus the notice, never an empty table.
          stopMock();
          setState((s) => ({ ...s, failed: true }));
        } else {
          startMock();
        }
      }
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelledRef.current = true;
      clearInterval(interval);
      stopMock();
    };
  }, []);

  return state;
}
