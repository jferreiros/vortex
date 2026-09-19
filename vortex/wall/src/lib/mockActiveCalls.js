// Simulated stand-in for GET /api/wall/calls/active, used by useActiveCalls
// whenever the real endpoint is missing or empty — the wall must always look
// alive for the demo. Same idea as mockTimeline.js, but it emits a fleet of
// calls instead of one call's timeline. The snapshot shape matches the
// documented endpoint contract plus one optional field (`patient_name`) the
// page uses once find_patient has resolved the caller.
//
// Emitted call: { call_id, from, started_ts, stage, intent, phase,
//                 tools_run, patient_name }

const TICK_MS = 750;
const MIN_CALLS = 8;
const MAX_CALLS = 12;

const NAMES = [
  "Lucía Ruiz López",
  "Antonio Pérez Gil",
  "María Torres Vidal",
  "Ana Salas Ferrer",
  "Jorge Nieto Campos",
  "Marcos Iglesias Peña",
  "Carmen Ortiz Serra",
  "Pau Vidal Roca",
  "Núria Casals Prat",
  "Iker Mendoza Ruiz",
  "Aitana Beltrán Gil",
  "Oier Agirre Sola",
  "Laia Font Bosch",
  "Bruno Castro León",
];

// Weighted pool: most calls end up booking, a few never classify cleanly and
// stay parked near the middle of the scatter.
const INTENT_POOL = [
  "book",
  "book",
  "book",
  "book",
  "reschedule",
  "reschedule",
  "cancel",
  "register",
  "no-action",
  "escalate",
  "question",
];

const TOOL_POOL = [
  "find_slots",
  "list_appointments",
  "validate_national_id",
  "prepare_booking",
  "prepare_reschedule",
  "prepare_cancel",
  "build_registration",
  "triage",
];

const PHASE_FLOW = {
  connecting: ["listening"],
  listening: ["thinking", "speaking", "listening"],
  thinking: ["working", "speaking", "listening"],
  working: ["speaking", "thinking", "listening"],
  speaking: ["listening", "thinking", "working"],
};

// Calls the line "already handled today" before this session opened — the
// header strip counts these plus whatever ends during the session.
const SEED_OUTCOMES = {
  book: 11,
  reschedule: 5,
  register: 2,
  cancel: 3,
  "no-action": 4,
  escalate: 2,
};

function rand(min, max) {
  return min + Math.random() * (max - min);
}

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

function maskedPhone(seq) {
  return `+34 6•• ••• ${String(100 + ((seq * 37) % 900))}`;
}

function newCall(seq, ageSeconds = 0) {
  const ageMs = ageSeconds * 1000;
  const willIdentify = Math.random() < 0.72;
  const willReclassify = Math.random() < 0.25;
  return {
    call_id: seq === 1 ? "demo" : `sim-${seq}`,
    from: maskedPhone(seq),
    started_ts: Date.now() - ageMs,
    stage: "listen",
    intent: null,
    phase: "connecting",
    tools_run: [],
    patient_name: null,
    _sim: {
      name: NAMES[(seq - 1) % NAMES.length],
      intentAt: rand(4, 10),
      identifyAt: willIdentify ? rand(8, 20) : null,
      reclassifyAt: willReclassify ? rand(24, 44) : null,
      toolAt: rand(10, 16),
      endAt: rand(50, 110),
      phaseUntil: 2.2,
    },
  };
}

function advancePhase(call, ageSeconds) {
  const sim = call._sim;
  if (ageSeconds < sim.phaseUntil) return;
  call.phase = pick(PHASE_FLOW[call.phase] || ["listening"]);
  sim.phaseUntil = ageSeconds + rand(2.5, 6.5);
}

function advanceCall(call, ageSeconds) {
  const sim = call._sim;
  advancePhase(call, ageSeconds);

  if (call.intent === null && ageSeconds >= sim.intentAt) {
    call.intent = pick(INTENT_POOL);
  }
  if (sim.reclassifyAt !== null && ageSeconds >= sim.reclassifyAt) {
    call.intent = pick(INTENT_POOL);
    sim.reclassifyAt = null;
  }
  if (sim.identifyAt !== null && ageSeconds >= sim.identifyAt) {
    if (!call.tools_run.includes("find_patient")) call.tools_run.push("find_patient");
    call.patient_name = sim.name;
    sim.identifyAt = null;
  }
  if (ageSeconds >= sim.toolAt && call.tools_run.length < 5) {
    const tool = pick(TOOL_POOL);
    if (call.tools_run[call.tools_run.length - 1] !== tool) call.tools_run.push(tool);
    sim.toolAt = ageSeconds + rand(9, 16);
  }

  call.stage = call.intent
    ? call.tools_run.length >= 3
      ? "submit"
      : "decide"
    : call.patient_name
      ? "decide"
      : ageSeconds > 2.5
        ? "identify"
        : "listen";
}

function toPublic(call) {
  const { _sim, ...pub } = call;
  return { ...pub, tools_run: [...pub.tools_run] };
}

// onUpdate receives { calls, stats } once per tick; returns a stop function.
export function mockActiveCallsStream(onUpdate) {
  let stopped = false;
  let seq = 0;
  const calls = new Map();
  const outcomes = { ...SEED_OUTCOMES };
  let completedToday = Object.values(SEED_OUTCOMES).reduce((a, b) => a + b, 0);

  function spawn(ageSeconds = 0) {
    seq += 1;
    const call = newCall(seq, ageSeconds);
    calls.set(call.call_id, call);
    return call;
  }

  function emit() {
    onUpdate({
      calls: [...calls.values()].map(toPublic),
      stats: { completed_today: completedToday, outcomes: { ...outcomes } },
    });
  }

  function tick() {
    if (stopped) return;
    const now = Date.now();
    for (const call of [...calls.values()]) {
      const ageSeconds = (now - call.started_ts) / 1000;
      if (ageSeconds >= call._sim.endAt) {
        calls.delete(call.call_id);
        completedToday += 1;
        const key = call.intent || "no-action";
        outcomes[key] = (outcomes[key] || 0) + 1;
        continue;
      }
      advanceCall(call, ageSeconds);
    }
    if (calls.size < MIN_CALLS || (calls.size < MAX_CALLS && Math.random() < 0.14)) {
      spawn();
    }
    emit();
  }

  // Seed a few calls already in flight — staggered ages so the first paint
  // shows a board mid-shift, not an empty room filling up. The first one is
  // the call_id "demo" so clicking through opens the scripted detail demo.
  for (const age of [38, 24, 14, 7, 2]) {
    const call = spawn(age);
    // Pre-play the milestones this age already passed.
    advanceCall(call, age);
    advanceCall(call, age);
  }
  // The "demo" call is the click-through anchor — pin it to a resolved,
  // mid-booking state so the first card is already a good story.
  const demo = calls.get("demo");
  demo.intent = "book";
  demo.patient_name = demo._sim.name;
  demo.tools_run = ["find_patient", "find_slots"];

  const interval = setInterval(tick, TICK_MS);
  emit();

  return () => {
    stopped = true;
    clearInterval(interval);
  };
}
