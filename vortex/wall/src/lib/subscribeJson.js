/* Open a Server-Sent Events URL and parse each `data:` line as JSON.

   Returns an EventSource, or null when the browser has no EventSource
   (so the caller can fall back to polling). Keep-alive comments (`: ping`)
   never fire `onmessage`. */

export function subscribeJson(url, onData) {
  if (typeof EventSource === "undefined") return null;
  const source = new EventSource(url);
  source.onmessage = (event) => {
    try {
      onData(JSON.parse(event.data));
    } catch {
      /* skip a malformed frame; the next one will replace it */
    }
  };
  return source;
}
