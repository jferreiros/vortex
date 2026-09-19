// Pure "Centro" picker logic for the Insights page, split out of
// Insights.jsx so it can run and be unit-tested (node:test) without a React
// render or JSX — no framework/dependency required either way.
//
// Both `occupancy` and `heatmap` follow the shape business_insights.py's
// service_occupancy() / demand_supply_heatmap() return: a network-wide
// view plus one entry per site under `sites`. "all" always reads the
// network-wide view; any other `site` id reads that site's own entry, and
// falls back to the network-wide numbers only for fields a site entry does
// not carry (`hoursLabel`, `suggestion`) or does not know at all — a
// missing/null per-site `rows`/`open` still falls back, which is exactly
// the bug that shipped once (see insightsData.js's history): every site's
// mock had `rows: null`, so picking a site silently kept showing the
// network-wide grid.

export function selectServices(occupancy, site) {
  if (site === "all") return occupancy?.all ?? [];
  return occupancy?.sites?.find((s) => s.id === site)?.services ?? [];
}

export function selectHeatmapView(heatmap, site) {
  const siteView = site !== "all" ? heatmap?.sites?.find((s) => s.id === site) : null;
  return {
    rows: siteView?.rows ?? heatmap?.rows,
    bands: heatmap?.bands,
    open: siteView?.open ?? heatmap?.open,
    hoursLabel: siteView?.hours_label ?? null,
    suggestion: site === "all" ? heatmap?.suggested_action : null,
  };
}
