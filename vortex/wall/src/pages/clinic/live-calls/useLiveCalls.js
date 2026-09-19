import { useEffect, useRef, useState } from "react";

/* The "in progress right now" feed, shared by Home and the call-detail pager.

   Starts empty and fills from GET /api/wall/live-calls. An empty real feed
   means no call in progress. A failed poll keeps the last good list. */

const POLL_MS = 4000;
const EMPTY = { calls: [], rejected: [], escalated: [] };

export function useLiveCalls() {
  const [feed, setFeed] = useState(EMPTY);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;

    async function poll() {
      try {
        const response = await fetch("/api/wall/live-calls");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const json = await response.json();
        if (cancelled.current || !Array.isArray(json?.calls)) return;
        setFeed({
          calls: json.calls,
          rejected: Array.isArray(json.rejected) ? json.rejected : EMPTY.rejected,
          escalated: Array.isArray(json.escalated) ? json.escalated : EMPTY.escalated,
        });
      } catch {
        // Keep the last good list — the mock on the very first failure.
      }
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelled.current = true;
      clearInterval(interval);
    };
  }, []);

  return feed;
}

export default useLiveCalls;
