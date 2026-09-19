// `node --test vortex/wall/tests/` — view-model maths for the two compact
// provider rankings ("Los más pedidos" / "Los que más citan"). Runs on
// plain Node, no deps.
import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { providerView } from "../src/pages/clinic/insights/providerView.js";

const payload = {
  providers: [
    { id: "PR01", name: "Dra. Ortiz", requests: 13, booked: 7, success_rate: 53.8, median_wait_days: 1.1 },
    { id: "PR02", name: "Dr. Sáez", requests: 11, booked: 0, success_rate: 0, median_wait_days: null },
    { id: "PR04", name: "Dra. Iglesias", requests: 6, booked: 0, success_rate: 0, median_wait_days: null },
    { id: "PR05", name: "Dr. Requena", requests: 3, booked: 1, success_rate: 33.3, median_wait_days: 3.1 },
    { id: "PR06", name: "D. Álvaro Cid", requests: 2, booked: 0, success_rate: 0, median_wait_days: 6.5 },
    { id: "PR07", name: "Dra. Poco", requests: 1, booked: 1, success_rate: 100, median_wait_days: 0.4 },
  ],
};

describe("providerView", () => {
  it("maps the endpoint JSON to points, preserving the row for drill-down", () => {
    const v = providerView(payload);
    const ortiz = v.points.find((p) => p.id === "PR01");
    assert.equal(ortiz.requests, 13);
    assert.equal(ortiz.successRate, 53.8);
    assert.equal(ortiz.waitDays, 1.1);
    assert.equal(ortiz.row, payload.providers[0]);
  });

  it("clinic rate is weighted: booked over all requests", () => {
    const v = providerView(payload);
    // 9 booked of 36 requests → 25%
    assert.equal(v.clinicRate, 25);
  });

  it("most-requested ranks by volume, capped at five", () => {
    const v = providerView(payload);
    assert.deepEqual(
      v.mostRequested.map((p) => p.id),
      ["PR01", "PR02", "PR04", "PR05", "PR06"]
    );
    // PR07's single request does not chart in the volume top 5 either.
    assert.equal(v.mostRequested.length, 5);
  });

  it("flagged means >= 2 requests and < 50% success — badge only on those", () => {
    const v = providerView(payload);
    assert.deepEqual(
      v.mostRequested.filter((p) => p.flagged).map((p) => p.id),
      ["PR02", "PR04", "PR05", "PR06"]
    );
    // PR01 (53.8%) and the 1-request PR07 (100%) are never flagged.
    assert.equal(v.points.find((p) => p.id === "PR01").flagged, false);
    assert.equal(v.points.find((p) => p.id === "PR07").flagged, false);
  });

  it("top closers excludes doctors under the request minimum", () => {
    const v = providerView(payload);
    // PR07's 1/1 = 100% must not top the ranking.
    assert.ok(!v.topClosers.some((p) => p.id === "PR07"));
    assert.equal(v.topClosers[0].id, "PR01");
    assert.deepEqual(
      v.topClosers.map((p) => p.id),
      ["PR01", "PR05", "PR02", "PR04", "PR06"]
    );
  });

  it("Referencia goes to the best closer who is not flagged — never a flagged one", () => {
    const v = providerView(payload);
    assert.equal(v.referenciaId, "PR01");
    const referencia = v.topClosers.find((p) => p.id === v.referenciaId);
    assert.equal(referencia.flagged, false);
  });

  it("a flagged doctor can chart in top closers but is never Referencia", () => {
    const v = providerView({
      providers: [
        { id: "F", name: "Dr. Flag", requests: 10, booked: 2, success_rate: 20 },
        { id: "G", name: "Dra. Good", requests: 5, booked: 4, success_rate: 80 },
      ],
    });
    assert.equal(v.mostRequested[0].id, "F");
    assert.equal(v.mostRequested[0].flagged, true);
    assert.equal(v.referenciaId, "G");
  });

  it("no non-flagged closer means no Referencia at all", () => {
    const v = providerView({
      providers: [{ id: "F", name: "Dr. Flag", requests: 4, booked: 1, success_rate: 25 }],
    });
    assert.equal(v.topClosers.length, 1);
    assert.equal(v.referenciaId, null);
  });

  it("empty payload yields no data and no rankings", () => {
    const v = providerView(null);
    assert.equal(v.hasData, false);
    assert.equal(v.clinicRate, null);
    assert.deepEqual(v.mostRequested, []);
    assert.deepEqual(v.topClosers, []);
    assert.equal(v.referenciaId, null);
  });
});
