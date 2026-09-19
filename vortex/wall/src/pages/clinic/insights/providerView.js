// View-model for the "Demanda por doctor" block: maps the raw
// /api/wall/business-insights `providers` payload to the two compact
// rankings the block draws — "Los más pedidos" (volume) and "Los que más
// citan" (close rate). Pure functions only — tested with `node --test`,
// no React and no DOM, so the same numbers the API emits are the numbers
// the tests assert on.

// The alert rule the block shows: a doctor is only "muy pedido, baja tasa"
// once real requests keep failing — one unlucky call never flags anyone.
export const MIN_REQUESTS = 2;
export const LOW_SUCCESS_PCT = 50;
export const RANKING_SIZE = 5;

const byName = (a, b) => a.name.localeCompare(b.name);

export function providerView(payload, { minRequests = MIN_REQUESTS } = {}) {
  const rows = payload?.providers ?? [];
  const points = rows.map((r) => {
    const requests = r.requests ?? 0;
    const successRate = r.success_rate ?? 0;
    return {
      id: r.id,
      name: r.name,
      requests,
      booked: r.booked ?? 0,
      successRate,
      waitDays: r.median_wait_days ?? null,
      // Computed here, not trusted from the payload, so the badge the
      // block paints follows exactly the rule it documents.
      flagged: requests >= minRequests && successRate < LOW_SUCCESS_PCT,
      row: r,
    };
  });

  // Clinic-wide rate is weighted — "qué % de todas las peticiones acaba
  // en cita", not the mean of per-doctor rates.
  const totalRequests = points.reduce((s, p) => s + p.requests, 0);
  const totalBooked = points.reduce((s, p) => s + p.booked, 0);
  const clinicRate =
    totalRequests > 0 ? Math.round((1000 * totalBooked) / totalRequests) / 10 : null;

  // Ranking 1: most requested, by volume.
  const mostRequested = [...points]
    .sort((a, b) => b.requests - a.requests || byName(a, b))
    .slice(0, RANKING_SIZE);
  const maxRequests = mostRequested[0]?.requests ?? 0;

  // Ranking 2: best closers, anti-noise — a 1/1 = 100% never charts.
  const topClosers = points
    .filter((p) => p.requests >= minRequests)
    .sort(
      (a, b) =>
        b.successRate - a.successRate || b.requests - a.requests || byName(a, b)
    )
    .slice(0, RANKING_SIZE);
  // "Referencia" goes to the best closer who is not an alert case — a
  // flagged doctor can rank here on rate alone but never leads.
  const referenciaId = topClosers.find((p) => !p.flagged)?.id ?? null;

  return {
    points,
    mostRequested,
    topClosers,
    maxRequests,
    referenciaId,
    clinicRate,
    hasData: points.length > 0,
  };
}
