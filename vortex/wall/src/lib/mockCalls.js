// Scripted call list for the Calls table's demo mode — the same derived row
// shape useCalls.deriveCall produces, so the page renders identically whether
// the line answers or not. A live call connects, runs through its phases,
// ends with an outcome, and a new one rings a few seconds later: the whole
// Retell pattern on a loop (the mockTimeline.js pattern, for a list).

const TICK_MS = 1000;
const LIVE_CALL_MS = 24_000;
const GAP_BETWEEN_CALLS_MS = 6_000;
const PATIENT_RESOLVES_MS = 10_000;
const INTENT_LANDS_MS = 8_000;

const PEOPLE = [
  { name: "Lucía Ruiz López", phone: "+34622334455" },
  { name: "Antonio Pérez Gil", phone: "+34600111222" },
  { name: "María Torres Vidal", phone: "+34655443322" },
  { name: "Jorge Nieto Campos", phone: "+34611223344" },
  { name: "Ana Salas Ferrer", phone: "+34699887766" },
];

// The outcome each live call lands, in cycle order.
const OUTCOMES = [
  { status: "booked", actionKind: "book", intent: "book" },
  { status: "refused", actionKind: "no-action", intent: "book", declineReason: "no_availability" },
  { status: "booked", actionKind: "book", intent: "book" },
  { status: "rescheduled", actionKind: "reschedule", intent: "reschedule" },
  { status: "escalated", actionKind: "escalate", intent: "escalate", declineReason: "medical_emergency" },
];

// Finished calls already on the log when the page opens. `recording` is set
// on the ones "with" a WAV: with no backend the player probes /recordings,
// gets a 404 and falls back to the muted "no recording" state — the same
// graceful path real calls take before the data-layer PR lands.
const HISTORY = [
  { id: "demo-c7", minutesAgo: 4, durationMs: 96_000, person: 0, status: "refused", actionKind: "no-action", intent: "book", declineReason: "no_availability", recording: true },
  { id: "demo-c6", minutesAgo: 11, durationMs: 141_000, person: 2, status: "escalated", actionKind: "escalate", intent: "escalate", declineReason: "medical_emergency", recording: true },
  { id: "demo-c5", minutesAgo: 19, durationMs: 78_000, person: 1, status: "booked", actionKind: "book", intent: "book", recording: true },
  { id: "demo-c4", minutesAgo: 27, durationMs: 61_000, person: null, status: "ended", recording: false },
  { id: "demo-c3", minutesAgo: 35, durationMs: 88_000, person: 3, status: "cancelled", actionKind: "cancel", intent: "cancel", recording: false },
  { id: "demo-c2", minutesAgo: 48, durationMs: 112_000, person: 4, status: "rescheduled", actionKind: "reschedule", intent: "reschedule", recording: true },
];

function finishedRow({ id, startedMs, durationMs, personIndex, status, actionKind, intent, declineReason, recording }) {
  const person = personIndex == null ? null : PEOPLE[personIndex];
  const endedMs = startedMs + durationMs;
  return {
    callId: id,
    startedAt: new Date(startedMs).toISOString(),
    startedMs,
    endedAt: new Date(endedMs).toISOString(),
    lastTs: new Date(endedMs).toISOString(),
    fromNumber: person ? person.phone : "+34622887140",
    fromMasked: null, // filled below via maskPhone-free format
    voice: "demo",
    clinic: "arenal",
    patientName: person ? person.name : null,
    patientId: person ? `P00${100 + personIndex}` : null,
    intent: intent || null,
    language: "es",
    actionKind: actionKind || null,
    submitStatus: actionKind ? "accepted" : null,
    declineReason: declineReason || null,
    endReason: "hangup",
    durationMs,
    recording: recording ? { format: "wav", durationMs } : null,
    ended: true,
    live: false,
    status,
    phase: "ended",
  };
}

function livePhase(elapsedMs) {
  if (elapsedMs < 2_000) return "connecting";
  if (elapsedMs < 6_000) return "listening";
  if (elapsedMs < 9_000) return "thinking";
  if (elapsedMs < 16_000) return "working";
  return "speaking";
}

export function mockCallsStream(onUpdate) {
  const history = HISTORY.map((def) =>
    finishedRow({
      id: def.id,
      startedMs: Date.now() - def.minutesAgo * 60_000,
      durationMs: def.durationMs,
      personIndex: def.person,
      status: def.status,
      actionKind: def.actionKind,
      intent: def.intent,
      declineReason: def.declineReason,
      recording: def.recording,
    }),
  );
  // Seed a couple of calls that finished during the current loop so ended
  // rows keep arriving, not just the static history.
  const ended = [];
  let liveSeq = 0;
  let liveStartMs = null;
  let nextRingAt = Date.now() + 1_200;
  let stopped = false;

  function rows(now) {
    const out = [];
    if (liveStartMs != null) {
      const elapsed = now - liveStartMs;
      const person = PEOPLE[liveSeq % PEOPLE.length];
      out.push({
        callId: `demo-live-${liveSeq}`,
        startedAt: new Date(liveStartMs).toISOString(),
        startedMs: liveStartMs,
        endedAt: null,
        lastTs: new Date(now).toISOString(),
        fromNumber: person.phone,
        fromMasked: null,
        voice: "demo",
        clinic: "arenal",
        patientName: elapsed >= PATIENT_RESOLVES_MS ? person.name : null,
        patientId: elapsed >= PATIENT_RESOLVES_MS ? `P00${200 + liveSeq}` : null,
        intent: elapsed >= INTENT_LANDS_MS ? OUTCOMES[liveSeq % OUTCOMES.length].intent : null,
        language: "es",
        actionKind: null,
        submitStatus: null,
        declineReason: null,
        endReason: null,
        durationMs: null,
        recording: null,
        ended: false,
        live: true,
        status: "live",
        phase: livePhase(elapsed),
      });
    }
    out.push(...ended, ...history);
    out.sort((a, b) => (b.startedMs ?? 0) - (a.startedMs ?? 0));
    // The mock writer masks phones itself — import cycle with useCalls.js
    // would be silly, and the masked shape is two characters of work.
    for (const row of out) {
      if (!row.fromMasked) {
        const digits = String(row.fromNumber).replace(/\D/g, "");
        row.fromMasked = `${String(row.fromNumber).slice(0, 4)}•••••${digits.slice(-3)}`;
      }
    }
    return out;
  }

  function tick() {
    if (stopped) return;
    const now = Date.now();
    if (liveStartMs == null && now >= nextRingAt) {
      liveSeq += 1;
      liveStartMs = now;
    }
    if (liveStartMs != null && now - liveStartMs >= LIVE_CALL_MS) {
      const outcome = OUTCOMES[liveSeq % OUTCOMES.length];
      ended.unshift(
        finishedRow({
          id: `demo-live-${liveSeq}`,
          startedMs: liveStartMs,
          durationMs: now - liveStartMs,
          personIndex: liveSeq % PEOPLE.length,
          status: outcome.status,
          actionKind: outcome.actionKind,
          intent: outcome.intent,
          declineReason: outcome.declineReason,
          recording: outcome.status !== "ended",
        }),
      );
      liveStartMs = null;
      nextRingAt = now + GAP_BETWEEN_CALLS_MS;
    }
    onUpdate(rows(now));
  }

  tick();
  const timer = setInterval(tick, TICK_MS);
  return () => {
    stopped = true;
    clearInterval(timer);
  };
}
