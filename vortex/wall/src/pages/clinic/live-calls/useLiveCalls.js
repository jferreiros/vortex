import { useEffect, useRef, useState } from "react";
import { PLACEHOLDER_CALLS } from "./placeholderCalls";

/* The "in progress right now" feed, shared by the Live Calls list and the
   detail pager so the two never disagree about which calls exist.

   It opens on PLACEHOLDER_CALLS and swaps to GET /api/wall/live-calls as
   soon as the first answer lands — including an empty one. An empty real
   feed means "no call in progress", which is a true and useful thing for
   the page to say; holding the demo calls there instead would be a lie the
   moment the line is quiet.

   A failed poll keeps whatever is on screen. The endpoint is served by the
   board itself, so a failure here means the board is going down anyway. */

const POLL_MS = 4000;

export function useLiveCalls() {
  const [calls, setCalls] = useState(PLACEHOLDER_CALLS);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;

    async function poll() {
      try {
        const response = await fetch("/api/wall/live-calls");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const json = await response.json();
        if (cancelled.current || !Array.isArray(json?.calls)) return;
        setCalls(json.calls);
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

  return calls;
}

export default useLiveCalls;
