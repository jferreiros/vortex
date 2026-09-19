import { useEffect, useState } from "react";
import { mockActiveCallsStream } from "./mockActiveCalls";

// Feeds /clinic/live-calls. Polls the board's fleet endpoint once a second;
// when it 404s or has nothing to say yet, a simulated stream takes over so
// the wall always has calls on it (mockTimeline.js plays the same role for
// the per-call detail). The only place the wire format matters is
// fetchActiveCalls below — when the data-layer PR lands, the real endpoint
// drops in with no changes anywhere else.
const POLL_MS = 1000;
const ENDPOINT = "/api/wall/calls/active";

// The API seam. One function deep on purpose.
async function fetchActiveCalls() {
  const res = await fetch(ENDPOINT);
  if (!res.ok) return null;
  const data = await res.json();
  return Array.isArray(data) ? data : null;
}

// The endpoint returns calls without call.ended, so "completadas hoy" and
// the outcome tally can only be learned by watching calls leave the list.
// Each departure counts once, under its last known intent.
function makeCompletionTracker() {
  const lastSeen = new Map();
  const tally = { completed: 0, outcomes: {} };
  return {
    update(calls) {
      const ids = new Set(calls.map((c) => c.call_id));
      for (const [id, prev] of lastSeen) {
        if (ids.has(id)) continue;
        lastSeen.delete(id);
        tally.completed += 1;
        const key = prev.intent || "no-action";
        tally.outcomes[key] = (tally.outcomes[key] || 0) + 1;
      }
      for (const call of calls) lastSeen.set(call.call_id, call);
      return { completed_today: tally.completed, outcomes: { ...tally.outcomes } };
    },
  };
}

// tools_run may arrive as ["find_patient", ...] or as richer objects when a
// lane has more to say — pull the tool names out either way, and the patient
// name with them if a find_patient result carries one.
function normalizeTools(toolsRun) {
  const names = [];
  let patientName = null;
  for (const entry of toolsRun || []) {
    if (typeof entry === "string") {
      names.push(entry);
      continue;
    }
    if (!entry || typeof entry !== "object") continue;
    const name = entry.name || entry.tool;
    if (name) names.push(name);
    const hit =
      entry.patient?.full_name || entry.patient_name || entry.result?.patient?.full_name || null;
    if (hit) patientName = hit;
  }
  return { names, patientName };
}

function toMs(value) {
  if (value == null) return null;
  if (typeof value === "number") return value > 1e12 ? value : value * 1000;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms;
}

// stage is the board's coarse step (listen / identify / decide / submit);
// when a call arrives without a phase, infer one so the wave still moves.
function phaseFromStage(stage) {
  switch (stage) {
    case "identify":
      return "working";
    case "decide":
      return "thinking";
    case "submit":
      return "working";
    default:
      return "listening";
  }
}

export function normalizeActiveCall(raw) {
  const tools = normalizeTools(raw?.tools_run);
  return {
    call_id: raw?.call_id ?? "unknown",
    from: raw?.from ?? raw?.from_masked ?? null,
    started_ms: toMs(raw?.started_ts ?? raw?.started_at),
    stage: raw?.stage ?? null,
    intent: raw?.intent ?? null,
    phase: raw?.phase ?? phaseFromStage(raw?.stage),
    tools_run: tools.names,
    name: raw?.patient_name ?? raw?.patient?.full_name ?? raw?.name ?? tools.patientName,
  };
}

export function useActiveCalls() {
  const [calls, setCalls] = useState([]);
  const [stats, setStats] = useState({ completed_today: 0, outcomes: {} });
  const [source, setSource] = useState("connecting");

  useEffect(() => {
    let cancelled = false;
    let stopMock = null;
    let sawRealData = false;
    const tracker = makeCompletionTracker();

    function startMock() {
      if (stopMock || cancelled) return;
      setSource("mock");
      stopMock = mockActiveCallsStream((snap) => {
        if (cancelled) return;
        setCalls(snap.calls.map(normalizeActiveCall));
        setStats(snap.stats);
      });
    }

    async function poll() {
      const data = await fetchActiveCalls().catch(() => null);
      // Trust the endpoint once it has produced real calls; until then an
      // error or an empty list just means "not up yet" -> run the mock.
      if (data === null || (data.length === 0 && !sawRealData)) {
        if (!sawRealData) startMock();
        return;
      }
      sawRealData = sawRealData || data.length > 0;
      // Real data wins: the mock hands the board off and never comes back.
      if (stopMock) {
        stopMock();
        stopMock = null;
      }
      const next = data.map(normalizeActiveCall);
      const nextStats = tracker.update(next);
      if (cancelled) return;
      setCalls(next);
      setStats(nextStats);
      setSource("live");
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
      if (stopMock) stopMock();
    };
  }, []);

  return { calls, stats, source };
}
