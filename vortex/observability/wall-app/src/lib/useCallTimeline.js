import { useEffect, useRef, useState } from "react";
import { mockStream } from "./mockTimeline";

// No call_id in the URL -> loop the scripted demo. Otherwise poll the real
// per-call timeline the Python board exposes at /api/wall/timeline/{id}.
// Returns { items, intent, call } — intent is the caller's detected intent
// and call is the header's data (duration, status, language, actions...),
// both kept separate from the chat/tool feed since neither is a chat message.
export function useCallTimeline(callId) {
  const [items, setItems] = useState([]);
  const [intent, setIntent] = useState(null);
  const [call, setCall] = useState(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;

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

    async function poll() {
      try {
        const res = await fetch(`/api/wall/timeline/${encodeURIComponent(callId)}`);
        if (!res.ok) return;
        const data = await res.json();
        if (cancelledRef.current) return;
        setItems(Array.isArray(data.items) ? data.items : []);
        setIntent(data.intent || null);
        setCall(data.call || null);
      } catch {
        // The board keeps polling; a dropped request just skips a frame.
      }
    }

    poll();
    const interval = setInterval(poll, 700);
    return () => {
      cancelledRef.current = true;
      clearInterval(interval);
    };
  }, [callId]);

  return { items, intent, call };
}
