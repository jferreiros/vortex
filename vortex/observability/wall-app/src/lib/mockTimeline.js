import { toolMeta } from "./tools";

// Pause after each step, in seconds. Bump this to slow the whole demo down —
// every delay below is this many seconds times the step's own weight.
const PACE_SECONDS = 4.2;

function makeScript(push, call, finish, setIntent, switchLanguage, bumpIdle, endCall, recordBooking) {
  return [
    { weight: 0.6, run: () => push({ type: "turn", role: "user", text: "Hola, quería pedir cita para mi hija." }) },
    { weight: 0.4, run: () => setIntent("book") },
    { weight: 1.1, run: () => push({ type: "turn", role: "assistant", text: "Claro. ¿Nombre completo y DNI de la paciente?" }) },
    { weight: 1.3, run: () => push({ type: "turn", role: "user", text: "Lucía Ruiz López, DNI 12345678Z." }) },
    {
      weight: 0.7,
      run: () => call("find_patient", { name: "Lucía Ruiz López", national_id: "12345678Z" }),
    },
    {
      weight: 1.6,
      run: () =>
        finish({
          status: "ok",
          ms: 2380,
          result: {
            status: "found",
            patient: {
              full_name: "Lucía Ruiz López",
              national_id: "12345678Z",
              phone: "+34612345678",
              date_of_birth: "2014-03-02",
            },
          },
        }),
    },
    { weight: 0.3, run: () => switchLanguage("es") },
    { weight: 1.1, run: () => push({ type: "turn", role: "assistant", text: "Perfecto, te tengo localizada. ¿Qué día te viene bien?" }) },
    { weight: 1.2, run: () => bumpIdle() },
    { weight: 1.0, run: () => push({ type: "turn", role: "user", text: "El jueves por la tarde si puede ser." }) },
    {
      weight: 0.6,
      run: () => call("find_slots", { date_from: "2026-09-22", date_to: "2026-09-27", specialty_id: "pediatria" }),
    },
    {
      weight: 1.4,
      run: () =>
        finish({
          status: "ok",
          ms: 1450,
          result: {
            slots: [
              { start: "2026-09-23T09:30:00+02:00" },
              { start: "2026-09-24T17:30:00+02:00" },
              { start: "2026-09-24T18:00:00+02:00" },
            ],
          },
        }),
    },
    { weight: 1.2, run: () => push({ type: "turn", role: "assistant", text: "Tengo un hueco el jueves a las 17:30 con el Dr. Ferreiro." }) },
    { weight: 1.1, run: () => push({ type: "turn", role: "user", text: "Perfecto, esa." }) },
    { weight: 0.6, run: () => call("validate_national_id", { value: "12345678Z" }) },
    { weight: 0.9, run: () => finish({ status: "ok", ms: 210, result: { valid: true } }) },
    { weight: 0.6, run: () => call("prepare_booking", { slot: "2026-09-24T17:30:00+02:00" }) },
    { weight: 1.1, run: () => finish({ status: "ok", ms: 480, result: { action: "book" } }) },
    { weight: 1.2, run: () => push({ type: "turn", role: "assistant", text: "Listo, cita confirmada para el jueves a las 17:30." }) },
    { weight: 0.6, run: () => call("submit_action", { route: "/api/v1/submit/book" }) },
    { weight: 1.0, run: () => finish({ status: "ok", ms: 900, result: { status: "accepted" } }) },
    { weight: 0.7, run: () => call("find_slots", { date_from: "2026-09-28", date_to: "2026-09-28" }) },
    {
      weight: 1.0,
      run: () => finish({ status: "ok", ms: 610, result: { slots: [{ start: "2026-09-28T12:00:00+02:00" }] } }),
    },
    { weight: 0.7, run: () => call("list_appointments", { patient_id: "P00107" }) },
    { weight: 1.0, run: () => finish({ status: "ok", ms: 540, result: { count: 2 } }) },
    { weight: 0.7, run: () => call("triage", { symptom: "fiebre" }) },
    { weight: 1.0, run: () => finish({ status: "ok", ms: 380, result: { route: "general" } }) },
    { weight: 0.7, run: () => call("find_patient", { phone: "+34600111222" }) },
    {
      weight: 1.6,
      run: () =>
        finish({
          status: "ok",
          ms: 2950,
          result: {
            status: "ambiguous",
            candidates: [
              { full_name: "Antonio Pérez Gil", national_id: "11111111H", phone: "+34600111222" },
              { full_name: "Ana Pérez Salas", national_id: "22222222J", phone: "+34600111222" },
            ],
          },
        }),
    },
    { weight: 0.4, run: () => switchLanguage("ca") },
    { weight: 1.4, run: () => push({ type: "turn", role: "assistant", text: "Que tinguis un bon dia." }) },
    // The call hangs up here without the booking confirmed yet — the header's
    // submit-window countdown starts ticking, then resolves a few seconds
    // later, same as a real accepted /api/v1/submit call landing late.
    { weight: 0.3, run: () => endCall() },
    { weight: 3.2, run: () => recordBooking() },
  ];
}

function makeInitialCall() {
  return {
    call_id: "demo",
    started_at: new Date().toISOString(),
    ended_at: null,
    live: true,
    status: "live",
    duration_ms: null,
    from_number: "+34622334455",
    voice: "pipecat",
    clinic: "arenal",
    action_kind: null,
    submit_status: null,
    submit_route: null,
    decline_reason: null,
    actions: [],
    language: null,
    language_history: [],
    idle_count: 0,
    submit_window_secs: 30,
  };
}

export function mockStream(onUpdate) {
  let items = [];
  let intent = null;
  let call = makeInitialCall();
  let startedAtMs = Date.now();
  let nextId = 1;
  let openTool = null;
  let timeoutId = null;
  let stopped = false;

  function emit() {
    onUpdate({ items: items.map((item) => ({ ...item })), intent, call: { ...call } });
  }

  function setIntent(value) {
    intent = value;
    emit();
  }

  function push(entry) {
    items.push({ id: nextId++, ts: Date.now(), ...entry });
    emit();
  }

  function callTool(tool, args) {
    const meta = toolMeta(tool);
    openTool = {
      id: nextId++,
      ts: Date.now(),
      type: "tool",
      tool,
      big: meta.big,
      status: "running",
      args,
      result: null,
      error: null,
      ms: null,
    };
    items.push(openTool);
    emit();
  }

  function finish({ status, result, error, ms }) {
    if (!openTool) return;
    openTool.status = status;
    openTool.result = result ?? null;
    openTool.error = error ?? null;
    openTool.ms = typeof ms === "number" ? ms : null;
    openTool = null;
    emit();
  }

  function switchLanguage(now) {
    const was = call.language;
    call = {
      ...call,
      language: now,
      language_history: [...call.language_history, { was, now, ts: new Date().toISOString() }],
    };
    emit();
  }

  function bumpIdle() {
    call = { ...call, idle_count: call.idle_count + 1 };
    emit();
  }

  function endCall() {
    call = {
      ...call,
      live: false,
      ended_at: new Date().toISOString(),
      duration_ms: Date.now() - startedAtMs,
    };
    emit();
  }

  function recordBooking() {
    call = {
      ...call,
      status: "booked",
      action_kind: "book",
      submit_status: "accepted",
      submit_route: "/api/v1/submit/book",
      actions: [
        ...call.actions,
        { route: "/api/v1/submit/book", payload: {}, result: { status: "accepted" } },
      ],
    };
    emit();
  }

  const script = makeScript(
    push,
    callTool,
    finish,
    setIntent,
    switchLanguage,
    bumpIdle,
    endCall,
    recordBooking,
  );

  function run(index) {
    if (stopped) return;
    if (index >= script.length) {
      timeoutId = setTimeout(() => {
        items = [];
        intent = null;
        call = makeInitialCall();
        startedAtMs = Date.now();
        nextId = 1;
        openTool = null;
        emit();
        run(0);
      }, PACE_SECONDS * 1.4 * 1000);
      return;
    }
    const step = script[index];
    step.run();
    const delay = Math.round(PACE_SECONDS * step.weight * 1000);
    timeoutId = setTimeout(() => run(index + 1), delay);
  }

  run(0);

  return () => {
    stopped = true;
    if (timeoutId) clearTimeout(timeoutId);
  };
}
