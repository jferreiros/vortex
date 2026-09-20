import { useEffect, useRef, useState } from "react";

const POLL_MS = 6000;

// What the page renders before GET /api/wall/home-overview answers, and
// whenever it has nothing to say: zeros, not invented numbers. A clinic
// reading its own morning page must never be shown a figure the line did
// not produce.
export const EMPTY_OVERVIEW = {
  as_of: null,
  window_days: 0,
  calls_in_window: 0,
  today: {
    calls: 0,
    ended: 0,
    booked: 0,
    registered: 0,
    rescheduled: 0,
    cancelled: 0,
    diary_touched: 0,
    contained_pct: null,
    escalated: 0,
    live: 0,
    needs_human: 0,
    human_reasons: [],
    mix: [],
  },
  unavailability: { unmet_total: 0, buckets: [], suggested_action: null },
  cancellations: {
    freed_total: 0,
    relocated: 0,
    lost: 0,
    pending: 0,
    recovery_rate_pct: null,
    suggested_action: null,
  },
};

function isHomeOverview(json) {
  return Boolean(json && json.today && typeof json.today.booked === "number");
}

/* Today's numbers, polled off the board's own API.

   Returns null until the first good answer lands, so a caller can tell
   "still loading" from "a real zero". A failed poll keeps the last good
   payload rather than dropping back to empty. */
export function useHomeOverview() {
  const [data, setData] = useState(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;

    async function poll() {
      try {
        const res = await fetch("/api/wall/home-overview");
        if (!res.ok || cancelledRef.current) return;
        const json = await res.json();
        if (cancelledRef.current) return;
        if (isHomeOverview(json)) setData(json);
      } catch {
        // Stay on whatever we already rendered.
      }
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelledRef.current = true;
      clearInterval(interval);
    };
  }, []);

  return data;
}
