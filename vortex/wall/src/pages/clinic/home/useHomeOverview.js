import { useEffect, useRef, useState } from "react";

const POLL_MS = 6000;

export const MOCK_OVERVIEW = {
  as_of: "2026-09-19T17:00:00+02:00",
  window_days: 7,
  calls_in_window: 214,
  today: {
    calls: 47,
    ended: 44,
    booked: 28,
    registered: 6,
    rescheduled: 5,
    cancelled: 4,
    diary_touched: 37,
    contained_pct: 86.4,
    escalated: 3,
    live: 3,
    needs_human: 6,
    human_reasons: [
      { key: "en_curso", label: "En curso", count: 3 },
      { key: "medical_emergency", label: "Urgencia médica", count: 2 },
      { key: "patient_not_found", label: "Paciente no identificado", count: 1 },
    ],
    mix: [
      { key: "book", label: "Concertadas", count: 28 },
      { key: "register", label: "Altas", count: 6 },
      { key: "reschedule", label: "Cambiadas", count: 5 },
      { key: "cancel", label: "Canceladas", count: 4 },
      { key: "no-action", label: "Sin cita", count: 1 },
      { key: "escalate", label: "A una persona", count: 3 },
      { key: "live", label: "En curso", count: 3 },
    ],
  },
  unavailability: {
    unmet_total: 19,
    buckets: [
      { key: "no_slot_in_window", label: "Sin hueco en la franja pedida", count: 9, share: 1, pct: 47.4 },
      { key: "provider_unavailable", label: "Médico concreto no disponible", count: 5, share: 0.556, pct: 26.3 },
      { key: "policy_not_covered", label: "Póliza no cubierta", count: 3, share: 0.333, pct: 15.8 },
      { key: "out_of_hours", label: "Fuera de horario", count: 2, share: 0.222, pct: 10.5 },
    ],
    suggested_action:
      "El 47% de la demanda no cubierta es por falta de hueco en la franja pedida, concentrado los jueves en la tarde: ampliar agenda ese tramo capturaría la mayor parte de esos rechazos.",
  },
  cancellations: {
    freed_total: 11,
    relocated: 7,
    lost: 3,
    pending: 1,
    recovery_rate_pct: 70,
    suggested_action:
      "De los 11 huecos liberados por cancelación, 7 se reubicaron (70%) pero 3 llegaron vacíos el día de la cita: avisar a la lista de espera en el instante de la cancelación recuperaría parte de esos huecos.",
  },
};

function isHomeOverview(json) {
  return Boolean(json && json.today && typeof json.today.booked === "number");
}

export function useHomeOverview() {
  const [data, setData] = useState(MOCK_OVERVIEW);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;

    async function poll() {
      try {
        const res = await fetch("/api/wall/home-overview");
        if (!res.ok || cancelledRef.current) return;
        const json = await res.json();
        if (cancelledRef.current) return;
        // Port 8080 may still be an older board whose home-overview has
        // stats/hourly charts and no `today` — adopting that payload
        // whitescreens this page. Keep the briefing mock until the
        // matching endpoint is up.
        if (isHomeOverview(json)) setData(json);
      } catch {
        // Stay on whatever we already rendered (the mock, or a previous good fetch).
      }
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelledRef.current = true;
      clearInterval(interval);
    };
  }, []);

  return data;
}
