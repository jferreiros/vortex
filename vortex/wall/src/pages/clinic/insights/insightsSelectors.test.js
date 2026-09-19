// Regression coverage for the "changing centro doesn't update the stats"
// bug: occupancy.sites used to share one array across every site, and
// heatmap.sites carried `rows: null` / `open: null`, so selectHeatmapView's
// `??` fallback silently kept showing the network-wide grid no matter which
// site was picked. Run with `node --test src` (node:test, no dependency).

import assert from "node:assert/strict";
import { test } from "node:test";
import { MOCK_STATS } from "./insightsData.js";
import { selectHeatmapView, selectServices } from "./insightsSelectors.js";

test("selectServices('all') returns the network-wide rows", () => {
  assert.deepEqual(selectServices(MOCK_STATS.occupancy, "all"), MOCK_STATS.occupancy.all);
});

test("selectServices(site) returns that site's own rows, not 'all'", () => {
  const centro = selectServices(MOCK_STATS.occupancy, "centro");
  assert.deepEqual(centro, MOCK_STATS.occupancy.sites[0].services);
  assert.notDeepEqual(centro, MOCK_STATS.occupancy.all);
});

test("selectServices differs between two real sites (the bug: every site was the same array)", () => {
  const centro = selectServices(MOCK_STATS.occupancy, "centro");
  const norte = selectServices(MOCK_STATS.occupancy, "norte");
  const sur = selectServices(MOCK_STATS.occupancy, "sur");
  assert.notDeepEqual(centro, norte);
  assert.notDeepEqual(centro, sur);
  assert.notDeepEqual(norte, sur);
});

test("selectServices falls back to [] for an unknown site id", () => {
  assert.deepEqual(selectServices(MOCK_STATS.occupancy, "does-not-exist"), []);
});

test("selectHeatmapView('all') returns the network-wide grid and its own suggestion", () => {
  const view = selectHeatmapView(MOCK_STATS.heatmap, "all");
  assert.deepEqual(view.rows, MOCK_STATS.heatmap.rows);
  assert.deepEqual(view.open, MOCK_STATS.heatmap.open);
  assert.equal(view.suggestion, MOCK_STATS.heatmap.suggested_action);
  assert.equal(view.hoursLabel, null);
});

test("selectHeatmapView(site) returns that site's own grid, not the network-wide one", () => {
  const centroSite = MOCK_STATS.heatmap.sites.find((s) => s.id === "centro");
  const view = selectHeatmapView(MOCK_STATS.heatmap, "centro");
  assert.deepEqual(view.rows, centroSite.rows);
  assert.deepEqual(view.open, centroSite.open);
  assert.equal(view.hoursLabel, centroSite.hours_label);
  // A per-site view never repeats the "all" suggestion — it has none of its own.
  assert.equal(view.suggestion, null);
  assert.notDeepEqual(view.rows, MOCK_STATS.heatmap.rows);
});

test("selectHeatmapView differs between two real sites (the bug: rows/open were null and always fell back)", () => {
  const centro = selectHeatmapView(MOCK_STATS.heatmap, "centro");
  const norte = selectHeatmapView(MOCK_STATS.heatmap, "norte");
  const sur = selectHeatmapView(MOCK_STATS.heatmap, "sur");
  assert.notDeepEqual(centro.rows, norte.rows);
  assert.notDeepEqual(centro.rows, sur.rows);
  assert.notDeepEqual(norte.rows, sur.rows);
  assert.notDeepEqual(centro.open, norte.open);
  assert.notDeepEqual(centro.open, sur.open);
});

test("selectHeatmapView still falls back to the network-wide grid when a site truly has none", () => {
  // A site entry with no rows/open of its own (e.g. a future site the log
  // has no per-site data for yet) is a legitimate case to fall back on —
  // only the mock data having this shape by mistake was the bug.
  const heatmap = {
    ...MOCK_STATS.heatmap,
    sites: [{ id: "nueva", name: "Arenal Nueva", hours_label: "L–V 09:00–13:00", open: null, rows: null }],
  };
  const view = selectHeatmapView(heatmap, "nueva");
  assert.deepEqual(view.rows, heatmap.rows);
  assert.deepEqual(view.open, heatmap.open);
  assert.equal(view.hoursLabel, "L–V 09:00–13:00");
});

test("every MOCK_STATS site has its own services array and heatmap grid (data-level guard)", () => {
  const serviceArrays = MOCK_STATS.occupancy.sites.map((s) => s.services);
  const rowArrays = MOCK_STATS.heatmap.sites.map((s) => s.rows);
  const openArrays = MOCK_STATS.heatmap.sites.map((s) => s.open);
  for (const arrays of [serviceArrays, rowArrays, openArrays]) {
    assert.ok(
      arrays.every((a) => a != null),
      "no site should carry a null services/rows/open in the shipped mock"
    );
    for (let i = 0; i < arrays.length; i += 1) {
      for (let j = i + 1; j < arrays.length; j += 1) {
        assert.notEqual(arrays[i], arrays[j], "two sites must not share the same array reference");
      }
    }
  }
});
