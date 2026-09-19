// Shared by the legacy server-registered entry (/call/{id}/zoom, still the
// only path FastAPI actually serves this SPA's index.html from — see
// vortex/observability/live.py) and the new app router. "demo" means: run
// the scripted no-backend demo, not a real poll. A real call_id never
// legitimately equals it.

export function resolveRawId(rawId) {
  const isDemo = !rawId || rawId === "demo";
  return {
    callId: isDemo ? null : rawId,
    isDemo,
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
  // Local Vite uses BrowserRouter (real paths). A copied "#/clinic/home"
  // would otherwise land on the landing page. Fold the hash into the path
  // before the router mounts.
  if (import.meta.env.DEV) {
    if (window.location.hash.startsWith("#/")) {
      window.history.replaceState(null, "", window.location.hash.slice(1));
    }
    return;
  }
  if (window.location.hash) return; // an explicit route was requested — respect it
  const { callId, isDemo } = resolveRawId(readServerPathId());
  if (!isDemo && callId) {
    window.location.hash = `#/clinic/live-calls/${encodeURIComponent(callId)}`;
  }
}
