import { useEffect, useRef, useState } from "react";
import { PLACEHOLDER_CALLS } from "./placeholderCalls";

// Calls still in progress right now, from GET /api/wall/live-calls — the
// line's own /calls first, the hosted Supabase call_events log as its
// automatic fallback when the line is unreachable, this process's JSONL
// last (see vortex.observability.callfeed.load_events, same order every
// other live card on the board reads). Shorter poll than Insights' 6 s:
// a call in progress moves fast enough that a stale "Escuchando" could
// outlive the whole turn it named.
const POLL_MS = 4000;

function isLiveCallsPayload(json) {
  return Boolean(json) && Array.isArray(json.calls);
}

// Home and Live Calls both read this so the two pages never disagree on
// who is on the line. Starts on the placeholder mock (today's dev-time
// fallback) and switches to the real feed — even an empty one, a
// genuinely true "nobody is calling right now" — on the first answer
// that actually has the shape this endpoint promises.
export function useLiveCalls() {
  const [calls, setCalls] = useState(PLACEHOLDER_CALLS);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;

    async function poll() {
      try {
        const res = await fetch("/api/wall/live-calls");
        if (!res.ok || cancelledRef.current) return;
        const json = await res.json();
        if (cancelledRef.current || !isLiveCallsPayload(json)) return;
        setCalls(json.calls);
      } catch {
        // Keep whatever is already on screen: the mock until the first
        // real answer lands, a real (possibly empty) list after that.
      }
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelledRef.current = true;
      clearInterval(interval);
    };
  }, []);

  return calls;
}
