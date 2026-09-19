// Shared by the legacy server-registered entry (/call/{id}/zoom, still the
// only path FastAPI actually serves this SPA's index.html from — see
// vortex/observability/live.py) and the new app router. "demo" and the
// reserved "design-N" ids mean: run the scripted no-backend demo, not a
// real poll. A real call_id never legitimately equals either.

const DESIGN_ID_RE = /^design-([1-9]|10|11)$/;

export function resolveRawId(rawId) {
  const designMatch = rawId && DESIGN_ID_RE.exec(rawId);
  const isDemo = !rawId || rawId === "demo" || Boolean(designMatch);
  return {
    callId: isDemo ? null : rawId,
    isDemo,
    designVariant: designMatch ? designMatch[1] : null,
  };
}

// Reads the id FastAPI put in the URL path before the SPA ever mounts a
// router (it's not part of the hash, so HashRouter never sees it). Used
// once, at boot, to decide where the app's HashRouter should start.
export function readServerPathId() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  const idx = parts.indexOf("call");
  const params = new URLSearchParams(window.location.search);
  return (idx >= 0 && parts[idx + 1] ? decodeURIComponent(parts[idx + 1]) : null) || params.get("call_id");
}

// A real, non-demo call_id in the server path should land the visitor
// straight on that call inside the app shell, not on the marketing
// landing page. Call once, before the router mounts.
export function bootstrapEntryHash() {
  if (window.location.hash) return; // an explicit route was requested — respect it
  const { callId, isDemo } = resolveRawId(readServerPathId());
  if (!isDemo && callId) {
    window.location.hash = `#/clinic/live-calls/${encodeURIComponent(callId)}`;
  }
}
