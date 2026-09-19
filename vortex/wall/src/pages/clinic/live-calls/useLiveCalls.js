import { useEffect, useRef, useState } from "react";
import { PLACEHOLDER_CALLS } from "./placeholderCalls";

/* The "in progress right now" feed, shared by Home, Live Calls, and the
   detail pager so the three never disagree about which calls exist.

   It opens on PLACEHOLDER_CALLS and swaps to GET /api/wall/live-calls as
   soon as the first answer lands — including an empty one. An empty real
   feed means "no call in progress", which is a true and useful thing for
   the page to say; holding the demo calls there instead would be a lie the
   moment the line is quiet.

   A failed poll keeps whatever is on screen. The endpoint is served by the
   board itself, so a failure here means the board is going down anyway. */

const POLL_MS = 4000;
const EMPTY = { calls: [], rejected: [], escalated: [] };

export function useLiveCalls() {
  const [feed, setFeed] = useState({
    calls: PLACEHOLDER_CALLS,
    rejected: [],
    escalated: [],
  });
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
