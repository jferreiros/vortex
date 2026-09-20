import { useEffect, useRef, useState } from "react";

// KPI briefing comes from GET /api/wall/home-overview (useHomeOverview.js).
// Occupancy is wall-cache/occupancy.json plus booked steps from the product
// database — see vortex/observability/home_pack.py.

export function useHomeOverview() {
  const [data, setData] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/wall/home-overview")
      .then((res) => (res.ok ? res.json() : null))
      .then((json) => {
        if (!cancelled) setData(json);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return data;
}

export function useOccupancy({ site, specialty } = {}) {
  const [data, setData] = useState(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    const params = new URLSearchParams();
    if (site) params.set("site", site);
    if (specialty) params.set("specialty", specialty);
    fetch(`/api/wall/occupancy?${params.toString()}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((json) => {
        if (!cancelledRef.current) setData(json);
      })
      .catch(() => {});
    return () => {
      cancelledRef.current = true;
    };
  }, [site, specialty]);

  return data;
}

// The chart components want a Date object (they call .getDate() and format
// with Intl.DateTimeFormat), the API answers with "YYYY-MM-DD" strings.
export function withDate(rows) {
  return (rows || []).map((r) => ({ ...r, date: new Date(`${r.date}T00:00:00`) }));
}

export function formatDuration(seconds) {
  if (seconds == null) return "—";
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
