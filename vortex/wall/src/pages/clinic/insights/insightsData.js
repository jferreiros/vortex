// Demo numbers for the Insights page, in the exact shape
// GET /api/wall/business-insights serves (business_insights.py). The page
// starts on these and only swaps in the live payload when it is rich enough
// to read (see Insights.jsx: isRichPayload) — a thin log paints a page full
// of zeros, which reads as "the product is broken", not "the day is young".
//
// Everything is derived from one 30-day base through `mockInsights(days)`,
// so the 7 / 30 / 90-day chips actually move the numbers and every derived
// figure (percentages, shares, occupancy, suggestions) stays consistent
// with the counts shown beside it.

const BASE_DAYS = 30;

// ---- what the line could not honour ---------------------------------------

const BASE_UNMET_BUCKETS = [
  { key: "no_slot_in_window", label: "No slot in the requested window", count: 17 },
  { key: "provider_unavailable", label: "Specific provider unavailable", count: 9 },
  { key: "policy_not_covered", label: "Policy not covered", count: 6 },
  { key: "out_of_hours", label: "Outside opening hours", count: 4 },
  { key: "referral_required", label: "Referral required", count: 2 },
];

// ---- cancellations ---------------------------------------------------------

const BASE_CANCELLATIONS = { freed_total: 24, relocated: 17, lost: 5, pending: 2 };

const BASE_CANCELLATION_DAILY = [
  { date: "2026-09-08", freed: 2, relocated: 2, lost: 0 },
  { date: "2026-09-09", freed: 1, relocated: 1, lost: 0 },
  { date: "2026-09-10", freed: 3, relocated: 2, lost: 1 },
  { date: "2026-09-11", freed: 2, relocated: 1, lost: 1 },
  { date: "2026-09-12", freed: 1, relocated: 1, lost: 0 },
  { date: "2026-09-14", freed: 3, relocated: 2, lost: 0 },
  { date: "2026-09-15", freed: 2, relocated: 2, lost: 0 },
  { date: "2026-09-16", freed: 2, relocated: 1, lost: 1 },
  { date: "2026-09-17", freed: 1, relocated: 1, lost: 0 },
  { date: "2026-09-18", freed: 3, relocated: 2, lost: 1 },
  { date: "2026-09-19", freed: 2, relocated: 1, lost: 1 },
  { date: "2026-09-20", freed: 2, relocated: 1, lost: 0 },
];

// ---- occupancy by service ---------------------------------------------------

// requested / offered / booked / declined_full / providers, per specialty.
const BASE_SERVICES = [
  ["general_practice", "General practice", 128, 96, 88, 14, 3],
  ["dermatology", "Dermatology", 46, 38, 33, 6, 1],
  ["paediatrics", "Paediatrics", 41, 52, 36, 1, 2],
  ["physiotherapy", "Physiotherapy", 37, 60, 31, 0, 1],
  ["orthopaedics", "Orthopaedics", 29, 44, 24, 1, 2],
  ["gynaecology", "Gynaecology", 22, 30, 19, 0, 1],
];

const BASE_SERVICES_CENTRO = [
  ["general_practice", "General practice", 71, 48, 47, 9, 2],
  ["dermatology", "Dermatology", 46, 38, 33, 6, 1],
  ["paediatrics", "Paediatrics", 24, 28, 21, 1, 1],
  ["physiotherapy", "Physiotherapy", 9, 16, 8, 0, 0],
  ["orthopaedics", "Orthopaedics", 17, 24, 14, 1, 1],
  ["gynaecology", "Gynaecology", 22, 30, 19, 0, 1],
];

const BASE_SERVICES_NORTE = [
  ["general_practice", "General practice", 39, 32, 28, 4, 1],
  ["dermatology", "Dermatology", 0, 0, 0, 0, 0],
  ["paediatrics", "Paediatrics", 17, 24, 15, 0, 1],
  ["physiotherapy", "Physiotherapy", 6, 12, 5, 0, 0],
  ["orthopaedics", "Orthopaedics", 12, 20, 10, 0, 1],
  ["gynaecology", "Gynaecology", 0, 0, 0, 0, 0],
];

const BASE_SERVICES_SUR = [
  ["general_practice", "General practice", 18, 16, 13, 1, 0],
  ["dermatology", "Dermatology", 0, 0, 0, 0, 0],
  ["paediatrics", "Paediatrics", 0, 0, 0, 0, 0],
  ["physiotherapy", "Physiotherapy", 22, 32, 18, 0, 1],
  ["orthopaedics", "Orthopaedics", 0, 0, 0, 0, 0],
  ["gynaecology", "Gynaecology", 0, 0, 0, 0, 0],
];

// ---- demand / supply heatmap ------------------------------------------------

export const BAND_NAMES = ["Morning", "Midday", "Afternoon", "Evening"];
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

// One [demand, availability] pair per band, per weekday.
const BASE_HEAT_ALL = [
  [[22, 18], [9, 12], [31, 16], [11, 6]],
  [[18, 18], [7, 11], [26, 19], [9, 3]],
  [[16, 16], [6, 10], [22, 21], [7, 4]],
  [[20, 13], [10, 7], [38, 4], [15, 1]],
  [[24, 20], [8, 10], [21, 17], [0, 0]],
  [[11, 8], [4, 3], [0, 0], [0, 0]],
  [[0, 0], [0, 0], [0, 0], [0, 0]],
];
const BASE_HEAT_CENTRO = [
  [[13, 10], [5, 6], [19, 9], [8, 4]],
  [[11, 10], [4, 6], [15, 11], [6, 2]],
  [[9, 9], [3, 5], [13, 12], [5, 3]],
  [[12, 7], [6, 4], [24, 2], [11, 1]],
  [[14, 11], [4, 5], [13, 10], [0, 0]],
  [[0, 0], [0, 0], [0, 0], [0, 0]],
  [[0, 0], [0, 0], [0, 0], [0, 0]],
];
const BASE_HEAT_NORTE = [
  [[6, 5], [3, 4], [9, 5], [3, 2]],
  [[5, 5], [2, 3], [8, 6], [3, 1]],
  [[5, 5], [2, 3], [6, 6], [2, 1]],
  [[6, 4], [3, 2], [11, 2], [4, 0]],
  [[7, 6], [3, 3], [6, 5], [0, 0]],
  [[11, 8], [4, 3], [0, 0], [0, 0]],
  [[0, 0], [0, 0], [0, 0], [0, 0]],
];
const BASE_HEAT_SUR = [
  [[3, 3], [1, 2], [3, 2], [0, 0]],
  [[2, 3], [1, 2], [3, 2], [0, 0]],
  [[2, 2], [1, 2], [3, 3], [0, 0]],
  [[2, 2], [1, 1], [3, 0], [0, 0]],
  [[3, 3], [1, 2], [2, 2], [0, 0]],
  [[0, 0], [0, 0], [0, 0], [0, 0]],
  [[0, 0], [0, 0], [0, 0], [0, 0]],
];

const OPEN_ALL = [
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, false],
  [true, true, false, false],
  [false, false, false, false],
];
export const MOCK_OPEN_CENTRO = [
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, false],
  [false, false, false, false],
  [false, false, false, false],
];
export const MOCK_OPEN_NORTE = [
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, false],
  [true, true, false, false],
  [false, false, false, false],
];
export const MOCK_OPEN_SUR = [
  [true, true, true, false],
  [true, true, true, false],
  [true, true, true, false],
  [true, true, true, false],
  [true, true, true, false],
  [false, false, false, false],
  [false, false, false, false],
];

// ---- scaling helpers --------------------------------------------------------

// Counts scale with the window; a 7-day window is not a flat 30/7th of the
// month (it holds this week's Thursday rush) and 90 days grows sub-linearly
// (the line only went live in the summer), so the factor is tuned, not
// proportional.
function factorFor(days) {
  if (days <= 7) return 0.31;
  if (days <= 30) return 1;
  return 2.6;
}

function scale(n, f) {
  if (!n) return 0;
  return Math.max(1, Math.round(n * f));
}

function pct(part, whole, digits = 1) {
  if (!whole) return 0;
  return Number(((100 * part) / whole).toFixed(digits));
}

function scaleUnmet(f) {
  const buckets = BASE_UNMET_BUCKETS.map((b) => ({ ...b, count: scale(b.count, f) }));
  const total = buckets.reduce((sum, b) => sum + b.count, 0);
  const top = buckets[0];
  const withShares = buckets.map((b) => ({
    ...b,
    share: Number((b.count / top.count).toFixed(3)),
    pct: pct(b.count, total),
  }));
  return {
    unmet_total: total,
    buckets: withShares,
    suggested_action:
      `${withShares[0].pct}% of unmet demand (${top.count} of ${total} calls) is a missing slot in the ` +
      "requested window, concentrated on Thursday afternoons at Arenal Centro: extending general " +
      "practice hours in that band would absorb most of these declines.",
  };
}

function scaleCancellations(f) {
  const freed = scale(BASE_CANCELLATIONS.freed_total, f);
  const relocated = scale(BASE_CANCELLATIONS.relocated, f);
  const pending = Math.min(scale(BASE_CANCELLATIONS.pending, f), Math.max(freed - relocated, 0));
  const lost = Math.max(freed - relocated - pending, 0);
  const rate = pct(relocated, freed, 0);
  const daily = f >= 1 ? BASE_CANCELLATION_DAILY : BASE_CANCELLATION_DAILY.slice(-5);
  return {
    freed_total: freed,
    relocated,
    lost,
    pending,
    recovery_rate_pct: rate,
    daily,
    lead_time: {
      count: freed,
      median_hours: 41,
      buckets: [
        { key: "under_24h", label: "< 24 h", count: scale(7, f), share: 0.29 },
        { key: "h24_48", label: "24–48 h", count: scale(6, f), share: 0.25 },
        { key: "h48_7d", label: "48 h – 7 d", count: scale(8, f), share: 0.33 },
        { key: "over_7d", label: "> 7 d", count: scale(3, f), share: 0.13 },
      ],
    },
    suggested_action:
      `Of the ${freed} slots freed by cancellation, ${relocated} were rebooked (${rate}%) but ` +
      `${lost} went unfilled on the appointment day, most of them cancelled under 24 h before: ` +
      "calling the waitlist the moment a cancellation lands would recover a good share of those.",
  };
}

function serviceRow([id, name, requested, offered, booked, declined, providers], f) {
  const req = requested ? scale(requested, f) : 0;
  const off = offered ? scale(offered, f) : 0;
  const bkd = booked ? Math.min(scale(booked, f), req) : 0;
  const occupancy = off ? pct(req, off) : requested ? null : 0;
  const extra = occupancy != null && occupancy > 110 && providers > 0 ? Math.ceil((req - off) / (off / providers)) : 0;
  return {
    id,
    name,
    requested: req,
    offered: off,
    booked: bkd,
    declined_full: declined ? scale(declined, f) : 0,
    providers,
    occupancy_pct: occupancy,
    extra_providers_needed: extra,
  };
}

function scaleServices(rows, f) {
  return rows.map((r) => serviceRow(r, f));
}

export function heatRow(weekday, pairs, f = 1) {
  const cells = BAND_NAMES.map((band, i) => ({
    band,
    demand: pairs[i][0] ? scale(pairs[i][0], f) : 0,
    availability: pairs[i][1] ? scale(pairs[i][1], f) : 0,
  }));
  return { weekday, all_day_demand: 0, cells };
}

function scaleHeat(grid, f) {
  return grid.map((pairs, i) => heatRow(WEEKDAYS[i], pairs, f));
}

function hottestGap(rows) {
  let best = null;
  rows.forEach((row) =>
    row.cells.forEach((cell) => {
      const gap = cell.demand - cell.availability;
      if (!best || gap > best.gap) best = { gap, weekday: row.weekday, ...cell };
    })
  );
  return best;
}

// ---- the payload ------------------------------------------------------------

export function mockInsights(days = BASE_DAYS) {
  const f = factorFor(days);
  const allRows = scaleHeat(BASE_HEAT_ALL, f);
  const gap = hottestGap(allRows);
  const services = scaleServices(BASE_SERVICES, f);
  const requested = services.reduce((sum, s) => sum + s.requested, 0);
  return {
    calls_considered: scale(412, f),
    unavailability: scaleUnmet(f),
    cancellations: scaleCancellations(f),
    occupancy: {
      all: services,
      sites: [
        { id: "centro", name: "Arenal Centro", services: scaleServices(BASE_SERVICES_CENTRO, f) },
        { id: "norte", name: "Arenal Norte", services: scaleServices(BASE_SERVICES_NORTE, f) },
        { id: "sur", name: "Arenal Sur", services: scaleServices(BASE_SERVICES_SUR, f) },
      ],
      requested_total: requested,
    },
    heatmap: {
      bands: [...BAND_NAMES],
      open: OPEN_ALL.map((row) => [...row]),
      rows: allRows,
      sites: [
        {
          id: "centro",
          name: "Arenal Centro",
          hours_label: "Mon–Thu 09:00–20:00 · Fri 09:00–17:00",
          open: MOCK_OPEN_CENTRO.map((row) => [...row]),
          rows: scaleHeat(BASE_HEAT_CENTRO, f),
        },
        {
          id: "norte",
          name: "Arenal Norte",
          hours_label: "Mon–Thu 09:00–20:00 · Fri 09:00–17:00 · Sat 09:00–14:00",
          open: MOCK_OPEN_NORTE.map((row) => [...row]),
          rows: scaleHeat(BASE_HEAT_NORTE, f),
        },
        {
          id: "sur",
          name: "Arenal Sur",
          hours_label: "Mon–Fri 09:00–17:00",
          open: MOCK_OPEN_SUR.map((row) => [...row]),
          rows: scaleHeat(BASE_HEAT_SUR, f),
        },
      ],
      suggested_action: gap
        ? `${gap.weekday} ${gap.band.toLowerCase()}s account for ${gap.demand} appointment requests with ` +
          `only ${gap.availability} slots offered in that band: opening the schedule there would capture ` +
          "the largest pool of unmet demand."
        : null,
    },
    providers: { providers: [] },
    data_gaps: [],
  };
}

// The 30-day view, for callers (and tests) that want one fixed payload.
export const MOCK_STATS = mockInsights(BASE_DAYS);
export const MOCK_UNAVAILABILITY = MOCK_STATS.unavailability;
export const MOCK_CANCELLATIONS = MOCK_STATS.cancellations;
export const MOCK_SERVICES = MOCK_STATS.occupancy.all;
export const MOCK_SERVICES_CENTRO = MOCK_STATS.occupancy.sites[0].services;
export const MOCK_SERVICES_NORTE = MOCK_STATS.occupancy.sites[1].services;
export const MOCK_SERVICES_SUR = MOCK_STATS.occupancy.sites[2].services;
export const MOCK_HEATMAP_CENTRO = MOCK_STATS.heatmap.sites[0].rows;
export const MOCK_HEATMAP_NORTE = MOCK_STATS.heatmap.sites[1].rows;
export const MOCK_HEATMAP_SUR = MOCK_STATS.heatmap.sites[2].rows;
