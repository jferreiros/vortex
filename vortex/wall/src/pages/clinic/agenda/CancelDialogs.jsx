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
  missing_doctor: "Elige un doctor.",
  missing_dates: "Elige las dos fechas.",
  unknown_doctor: "No se encontró ese doctor.",
  bad_request: "La petición no es válida.",
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
      setError(RANGE_ERRORS[payload.error] || "No se pudo contar las citas.");
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
      setError(RANGE_ERRORS[payload.error] || "No se pudo cancelar.");
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
      title="Cancelar citas"
      onClose={onClose}
      actions={
        done ? (
          <Button variant="primary" type="button" onClick={onClose}>Cerrar</Button>
        ) : (
          <>
            <Button variant="ghost" type="button" onClick={onClose}>Volver</Button>
            {ready ? (
              <Button
                variant="danger"
                type="button"
                disabled={busy || preview.count === 0}
                onClick={runCancel}
              >
                {busy ? "Cancelando…" : `Confirmar: cancelar ${preview.count} cita${preview.count === 1 ? "" : "s"}`}
              </Button>
            ) : (
              <Button
                variant="secondary"
                type="button"
                disabled={!valid || busy}
                onClick={runPreview}
              >
                {busy ? "Contando…" : "Ver citas afectadas"}
              </Button>
            )}
          </>
        )
      }
    >
      {done ? (
        <p className="agenda-cancel-note">
          {result.cancelled === 0
            ? "No había citas en ese rango."
            : `Hecho: ${result.cancelled} cita${result.cancelled === 1 ? "" : "s"} de ${result.doctor} cancelada${result.cancelled === 1 ? "" : "s"}.`}
          {result.rebookings_queued > 0 &&
            ` Se llamará a ${result.rebookings_queued} paciente${result.rebookings_queued === 1 ? "" : "s"} para buscar otro hueco.`}
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
              <option value="">Elige un doctor</option>
              {doctors.map((row) => (
                <option key={row.id || row.name} value={row.id}>{row.name}</option>
              ))}
            </select>
          </div>
          <div className="agenda-cancel-row">
            <div className="agenda-field">
              <label htmlFor="cancel-from">Desde</label>
              <input
                id="cancel-from"
                type="date"
                className="agenda-date"
                value={from}
                onChange={(e) => { setFrom(e.target.value); edit(); }}
              />
            </div>
            <div className="agenda-field">
              <label htmlFor="cancel-to">Hasta</label>
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
                  ? `${preview.doctor} no tiene citas entre el ${fmtDay(from)} y el ${fmtDay(to)}.`
                  : `Se cancelarán ${preview.count} cita${preview.count === 1 ? "" : "s"} de ${preview.doctor} entre el ${fmtDay(from)} y el ${fmtDay(to)}.`}
              </p>
              {preview.sample?.length > 0 && (
                <ul className="agenda-cancel-list">
                  {preview.sample.map((row, i) => (
                    <li key={i}>{fmtDay(row.date)} · {row.time} — {row.full_name}</li>
                  ))}
                  {preview.count > preview.sample.length && (
                    <li>…y {preview.count - preview.sample.length} más</li>
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
          ? "Esa cita ya no existe en la agenda."
          : "No se pudo cancelar la cita."
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
      title="Cancelar esta cita"
      onClose={onClose}
      actions={
        <>
          <Button variant="ghost" type="button" onClick={onClose}>Mantener cita</Button>
          <Button variant="danger" type="button" disabled={busy} onClick={runCancel}>
            {busy ? "Cancelando…" : "Sí, cancelar la cita"}
          </Button>
        </>
      }
    >
      {visit && (
        <div className="agenda-cancel-fields">
          <p className="agenda-cancel-note">¿Estás seguro? Se cancelará esta cita:</p>
          <dl className="agenda-kv">
            <div><dt>Paciente</dt><dd>{visit.full_name}</dd></div>
            <div><dt>Doctor</dt><dd>{doctorName || visit.provider_name || "—"}</dd></div>
            <div><dt>Cuándo</dt><dd>{visit.when}</dd></div>
            <div><dt>Centro</dt><dd>{visit.location_name || "—"}</dd></div>
          </dl>
          <p className="agenda-cancel-note">
            El paciente pasará a la cola de reagendado: se le llamará para buscar otro hueco.
          </p>
          {error && <p className="agenda-error">{error}</p>}
        </div>
      )}
    </Modal>
  );
}
