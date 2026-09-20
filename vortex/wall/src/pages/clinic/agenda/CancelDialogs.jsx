import { useEffect, useState } from "react";
import Modal from "../../../components/ui/Modal";
import Button from "../../../components/ui/Button";

// The two ways Horarios cancels appointments. Both post to the board's own
// API (vortex/observability/live.py): /api/wall/agenda/cancel-preview +
// /api/wall/agenda/cancel for the range, /api/wall/appointments/cancel for a
// single visit. The write lands in database/'s wall_cancellations table; the
// parent refetches the agenda on onDone and the freed slots just disappear.
// Neither path cancels without an explicit confirm press.

function isoPlusDays(iso, days) {
  const [y, m, d] = iso.split("-").map(Number);
  const next = new Date(y, m - 1, d + days);
  const mm = String(next.getMonth() + 1).padStart(2, "0");
  const dd = String(next.getDate()).padStart(2, "0");
  return `${next.getFullYear()}-${mm}-${dd}`;
}

function fmtDay(iso) {
  return iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "";
}

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await res.json().catch(() => ({}));
  return { status: res.status, payload };
}

const RANGE_ERRORS = {
  missing_doctor: "Choose a doctor.",
  missing_dates: "Choose both dates.",
  unknown_doctor: "That doctor wasn't found.",
  bad_request: "The request isn't valid.",
};

export function CancelRangeDialog({ open, onClose, doctors, initialProviderId, today, onDone }) {
  const [providerId, setProviderId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [phase, setPhase] = useState("edit"); // edit -> ready -> done
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setProviderId(initialProviderId || "");
    setFrom(today || "");
    setTo(today ? isoPlusDays(today, 7) : "");
    setPhase("edit");
    setPreview(null);
    setResult(null);
    setBusy(false);
    setError("");
  }, [open, initialProviderId, today]);

  function edit() {
    // Any field change invalidates the count — the confirm button can never
    // fire on a stale preview.
    setPhase("edit");
    setPreview(null);
    setError("");
  }

  async function runPreview() {
    setBusy(true);
    setError("");
    const { payload } = await post("/api/wall/agenda/cancel-preview", {
      provider_id: providerId,
      from,
      to,
    });
    setBusy(false);
    if (!payload.ok) {
      setError(RANGE_ERRORS[payload.error] || "Couldn't count the appointments.");
      return;
    }
    setPreview(payload);
    setPhase("ready");
  }

  async function runCancel() {
    setBusy(true);
    setError("");
    const { payload } = await post("/api/wall/agenda/cancel", {
      provider_id: providerId,
      from,
      to,
    });
    setBusy(false);
    if (!payload.ok) {
      setError(RANGE_ERRORS[payload.error] || "Couldn't cancel.");
      return;
    }
    setResult(payload);
    setPhase("done");
    onDone();
  }

  const ready = phase === "ready" && preview;
  const done = phase === "done" && result;
  const valid = providerId && from && to;

  return (
    <Modal
      open={open}
      title="Cancel appointments"
      onClose={onClose}
      actions={
        done ? (
          <Button variant="primary" type="button" onClick={onClose}>Close</Button>
        ) : (
          <>
            <Button variant="ghost" type="button" onClick={onClose}>Back</Button>
            {ready ? (
              <Button
                variant="danger"
                type="button"
                disabled={busy || preview.count === 0}
                onClick={runCancel}
              >
                {busy ? "Cancelling…" : `Confirm: cancel ${preview.count} appointment${preview.count === 1 ? "" : "s"}`}
              </Button>
            ) : (
              <Button
                variant="secondary"
                type="button"
                disabled={!valid || busy}
                onClick={runPreview}
              >
                {busy ? "Counting…" : "View affected appointments"}
              </Button>
            )}
          </>
        )
      }
    >
      {done ? (
        <p className="agenda-cancel-note">
          {result.cancelled === 0
            ? "There were no appointments in that range."
            : `Done: ${result.cancelled} appointment${result.cancelled === 1 ? "" : "s"} for ${result.doctor} cancelled.`}
          {result.rebookings_queued > 0 &&
            ` ${result.rebookings_queued} patient${result.rebookings_queued === 1 ? "" : "s"} will be called to find another slot.`}
        </p>
      ) : (
        <div className="agenda-cancel-fields">
          <div className="agenda-field">
            <label htmlFor="cancel-doctor">Doctor</label>
            <select
              id="cancel-doctor"
              className="ui-select"
              value={providerId}
              onChange={(e) => { setProviderId(e.target.value); edit(); }}
            >
              <option value="">Choose a doctor</option>
              {doctors.map((row) => (
                <option key={row.id || row.name} value={row.id}>{row.name}</option>
              ))}
            </select>
          </div>
          <div className="agenda-cancel-row">
            <div className="agenda-field">
              <label htmlFor="cancel-from">From</label>
              <input
                id="cancel-from"
                type="date"
                className="agenda-date"
                value={from}
                onChange={(e) => { setFrom(e.target.value); edit(); }}
              />
            </div>
            <div className="agenda-field">
              <label htmlFor="cancel-to">To</label>
              <input
                id="cancel-to"
                type="date"
                className="agenda-date"
                value={to}
                onChange={(e) => { setTo(e.target.value); edit(); }}
              />
            </div>
          </div>
          {ready && (
            <div className="agenda-cancel-preview">
              <p className="agenda-cancel-note">
                {preview.count === 0
                  ? `${preview.doctor} has no appointments between ${fmtDay(from)} and ${fmtDay(to)}.`
                  : `${preview.count} appointment${preview.count === 1 ? "" : "s"} for ${preview.doctor} will be cancelled between ${fmtDay(from)} and ${fmtDay(to)}.`}
              </p>
              {preview.sample?.length > 0 && (
                <ul className="agenda-cancel-list">
                  {preview.sample.map((row, i) => (
                    <li key={i}>{fmtDay(row.date)} · {row.time} — {row.full_name}</li>
                  ))}
                  {preview.count > preview.sample.length && (
                    <li>…and {preview.count - preview.sample.length} more</li>
                  )}
                </ul>
              )}
            </div>
          )}
          {error && <p className="agenda-error">{error}</p>}
        </div>
      )}
    </Modal>
  );
}

export function CancelVisitDialog({ visit, doctorName, onClose, onDone }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (visit) {
      setBusy(false);
      setError("");
    }
  }, [visit]);

  async function runCancel() {
    setBusy(true);
    setError("");
    const { payload } = await post("/api/wall/appointments/cancel", {
      provider_id: visit.provider_id,
      location_id: visit.location_id,
      slot_start: visit.slot,
    });
    setBusy(false);
    if (!payload.ok) {
      setError(
        payload.error === "not_booked"
          ? "That appointment no longer exists in the schedule."
          : "Couldn't cancel the appointment."
      );
      if (payload.error === "not_booked") onDone();
      return;
    }
    onDone();
    onClose();
  }

  return (
    <Modal
      open={Boolean(visit)}
      title="Cancel this appointment"
      onClose={onClose}
      actions={
        <>
          <Button variant="ghost" type="button" onClick={onClose}>Keep appointment</Button>
          <Button variant="danger" type="button" disabled={busy} onClick={runCancel}>
            {busy ? "Cancelling…" : "Yes, cancel the appointment"}
          </Button>
        </>
      }
    >
      {visit && (
        <div className="agenda-cancel-fields">
          <p className="agenda-cancel-note">Are you sure? This appointment will be cancelled:</p>
          <dl className="agenda-kv">
            <div><dt>Patient</dt><dd>{visit.full_name}</dd></div>
            <div><dt>Doctor</dt><dd>{doctorName || visit.provider_name || "—"}</dd></div>
            <div><dt>When</dt><dd>{visit.when}</dd></div>
            <div><dt>Site</dt><dd>{visit.location_name || "—"}</dd></div>
          </dl>
          <p className="agenda-cancel-note">
            The patient will move to the reschedule queue: they will be called to find another slot.
          </p>
          {error && <p className="agenda-error">{error}</p>}
        </div>
      )}
    </Modal>
  );
}
