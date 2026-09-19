import { STATUS_LABEL } from "./labels";

// Shared derivations, pulled out of the original App/LeftPane/InsightPanel so
// every design concept reads the same call state the same way. Presentation
// differs per concept; the rules that produce "what is true right now" do not.

const ACCEPTED_STATUSES = new Set(["accepted", "duplicate"]);

export function deriveFinalAction(call) {
  if (!call) {
    return { label: "—", muted: true, accepted: false, duplicateBlocked: false, showCountdown: false };
  }
  const actions = call.actions || [];
  const accepted = actions.some((a) => ACCEPTED_STATUSES.has(a?.result?.status));
  const duplicateBlocked = actions.some((a) => a?.result?.status === "duplicate");
  const endedMs = call.ended_at ? new Date(call.ended_at).getTime() : null;
  const windowSecs = call.submit_window_secs ?? 30;
  const submitElapsed = !call.live && endedMs ? (Date.now() - endedMs) / 1000 : 0;
  const submitRemaining = windowSecs - submitElapsed;
  const showCountdown = !call.live && !accepted && submitRemaining > -8;
  const label = call.live ? "En curso…" : STATUS_LABEL[call.status] || call.status || "—";
  return { label, muted: false, accepted, duplicateBlocked, showCountdown, submitRemaining, live: call.live };
}
