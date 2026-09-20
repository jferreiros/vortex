import { useEffect, useRef, useState } from "react";
import { subscribeJson } from "../../../lib/subscribeJson";

/* The "in progress right now" feed, shared by Home and the call-detail pager.

   Prefers GET /api/wall/live-calls/stream (SSE). Falls back to polling
   GET /api/wall/live-calls when EventSource is missing or the stream
   errors before the first frame. An empty real feed means no call in
   progress. A failed poll keeps the last good list. */

const POLL_MS = 4000;
const EMPTY = { calls: [], rejected: [], escalated: [] };

function applyFeed(json) {
  if (!Array.isArray(json?.calls)) return null;
  return {
    calls: json.calls,
    rejected: Array.isArray(json.rejected) ? json.rejected : EMPTY.rejected,
    escalated: Array.isArray(json.escalated) ? json.escalated : EMPTY.escalated,
  };
}

export function useLiveCalls() {
  const [feed, setFeed] = useState(EMPTY);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    let interval = null;

    async function poll() {
      try {
        const response = await fetch("/api/wall/live-calls");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const next = applyFeed(await response.json());
        if (cancelled.current || !next) return;
        setFeed(next);
      } catch {
        // Keep the last good list.
      }
    }

    function startPoll() {
      if (interval != null) return;
      poll();
      interval = setInterval(poll, POLL_MS);
    }

    let gotFrame = false;
    const source = subscribeJson("/api/wall/live-calls/stream", (json) => {
      gotFrame = true;
      const next = applyFeed(json);
      if (cancelled.current || !next) return;
      setFeed(next);
    });

    if (source) {
      source.onerror = () => {
        if (cancelled.current) return;
        if (!gotFrame) {
          source.close();
          startPoll();
        }
      };
    } else {
      startPoll();
    }

    return () => {
      cancelled.current = true;
      if (source) source.close();
      if (interval != null) clearInterval(interval);
    };
  }, []);

  return feed;
}

export default useLiveCalls;
