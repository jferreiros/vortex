// Fires a full-screen wipe transition (see PageWipeOverlay.jsx) from
// anywhere in the tree, then navigates once the wipe has fully covered the
// screen. A tiny event emitter rather than context: the trigger and the
// overlay (mounted once at the router root, so it survives the route
// change) don't share a parent.
const listeners = new Set();

export function triggerPageWipe(toPath) {
  listeners.forEach((fn) => fn(toPath));
}

export function onPageWipe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
