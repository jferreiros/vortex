import { useEffect, useRef, useState } from "react";
import { mockStream } from "./mockTimeline";
import { subscribeJson } from "./subscribeJson";

const POLL_MS = 700;

function applyTimeline(data, setItems, setIntent, setCall) {
  setItems(Array.isArray(data.items) ? data.items : []);
  setIntent(data.intent || null);
  setCall(data.call || null);
}

// No call_id in the URL -> loop the scripted demo. Otherwise subscribe to
// GET /api/wall/timeline/{id}/stream (SSE) and fall back to polling the
// same JSON if EventSource is missing or the stream errors before a frame.
export function useCallTimeline(callId) {
  const [items, setItems] = useState([]);
  const [intent, setIntent] = useState(null);
  const [call, setCall] = useState(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    setItems([]);
    setIntent(null);
    setCall(null);

    if (!callId) {
      const stop = mockStream((next) => {
        if (cancelledRef.current) return;
        setItems(next.items);
        setIntent(next.intent);
        setCall(next.call);
      });
      return () => {
        cancelledRef.current = true;
        stop();
      };
    }

    const url = `/api/wall/timeline/${encodeURIComponent(callId)}/stream`;
    let interval = null;

    async function poll() {
      try {
        const res = await fetch(`/api/wall/timeline/${encodeURIComponent(callId)}`);
        if (!res.ok) return;
        const data = await res.json();
        if (cancelledRef.current) return;
        applyTimeline(data, setItems, setIntent, setCall);
      } catch {
        // A dropped request just skips a frame.
      }
    }

    function startPoll() {
      if (interval != null) return;
      poll();
      interval = setInterval(poll, POLL_MS);
    }

    let gotFrame = false;
    const source = subscribeJson(url, (data) => {
      gotFrame = true;
      if (cancelledRef.current) return;
      applyTimeline(data, setItems, setIntent, setCall);
    });

    if (source) {
      source.onerror = () => {
        if (cancelledRef.current) return;
        if (!gotFrame) {
          source.close();
          startPoll();
        }
      };
    } else {
      startPoll();
    }

    return () => {
      cancelledRef.current = true;
      if (source) source.close();
      if (interval != null) clearInterval(interval);
    };
  }, [callId]);

  return { items, intent, call };
}
