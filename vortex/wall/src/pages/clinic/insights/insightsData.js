
// Placeholder numbers for the panels whose real endpoint is not wired yet.
// Everything the board already serves (Home, live calls, business insights)
// reads its own API; these are the leftovers, kept together so the next
// endpoint to land can delete its block outright.
export const MOCK_UNAVAILABILITY = {
  unmet_total: 19,
  buckets: [
    { key: "no_slot_in_window", label: "No slot in the requested window", count: 9, share: 1, pct: 47.4 },
    { key: "provider_unavailable", label: "Specific provider unavailable", count: 5, share: 0.556, pct: 26.3 },
    { key: "policy_not_covered", label: "Policy not covered", count: 3, share: 0.333, pct: 15.8 },
    { key: "out_of_hours", label: "Outside opening hours", count: 2, share: 0.222, pct: 10.5 },
  ],
  suggested_action:
    "47% of unmet demand is due to no slot in the requested window, concentrated on Thursday afternoons: extending the schedule for that slot would capture most of these declines.",
};

export const MOCK_CANCELLATIONS = {
  freed_total: 11,
  relocated: 7,
  lost: 3,
  pending: 1,
  recovery_rate_pct: 70,
  suggested_action:
    "Of the 11 slots freed by cancellation, 7 were rebooked (70%) but 3 went unfilled on the appointment day: notifying the waitlist the moment a cancellation happens would recover some of those slots.",
};

// One mock row per catalogue specialty — the six Arenal services, network-wide.
export const MOCK_SERVICES = [
  { id: "general_practice", name: "General practice", requested: 21, offered: 18, booked: 15, declined_full: 3, providers: 3, occupancy_pct: 116.7, extra_providers_needed: 1 },
  { id: "paediatrics", name: "Paediatrics", requested: 9, offered: 12, booked: 8, declined_full: 0, providers: 2, occupancy_pct: 75.0, extra_providers_needed: 0 },
  { id: "dermatology", name: "Dermatology", requested: 6, offered: 8, booked: 5, declined_full: 0, providers: 1, occupancy_pct: 75.0, extra_providers_needed: 0 },
  { id: "orthopaedics", name: "Orthopaedics", requested: 5, offered: 10, booked: 4, declined_full: 0, providers: 2, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "gynaecology", name: "Gynaecology", requested: 3, offered: 6, booked: 3, declined_full: 0, providers: 1, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "physiotherapy", name: "Physiotherapy", requested: 2, offered: 9, booked: 2, declined_full: 0, providers: 1, occupancy_pct: 22.2, extra_providers_needed: 0 },
];

// Per-site mock rows, distinct from each other and from the network-wide
// total above — the real service_occupancy() scopes every count to one
// site's own find_slots calls, so these three must actually differ or the
// site picker looks broken even when the wiring is correct.
export const MOCK_SERVICES_CENTRO = [
  { id: "general_practice", name: "General practice", requested: 12, offered: 10, booked: 9, declined_full: 2, providers: 2, occupancy_pct: 120.0, extra_providers_needed: 1 },
  { id: "paediatrics", name: "Paediatrics", requested: 5, offered: 6, booked: 4, declined_full: 0, providers: 1, occupancy_pct: 83.3, extra_providers_needed: 0 },
  { id: "dermatology", name: "Dermatology", requested: 4, offered: 5, booked: 3, declined_full: 0, providers: 1, occupancy_pct: 80.0, extra_providers_needed: 0 },
  { id: "orthopaedics", name: "Orthopaedics", requested: 3, offered: 6, booked: 3, declined_full: 0, providers: 1, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "gynaecology", name: "Gynaecology", requested: 2, offered: 4, booked: 2, declined_full: 0, providers: 1, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "physiotherapy", name: "Physiotherapy", requested: 1, offered: 5, booked: 1, declined_full: 0, providers: 1, occupancy_pct: 20.0, extra_providers_needed: 0 },
];
export const MOCK_SERVICES_NORTE = [
  { id: "general_practice", name: "General practice", requested: 6, offered: 5, booked: 4, declined_full: 1, providers: 1, occupancy_pct: 120.0, extra_providers_needed: 1 },
  { id: "paediatrics", name: "Paediatrics", requested: 3, offered: 4, booked: 3, declined_full: 0, providers: 1, occupancy_pct: 75.0, extra_providers_needed: 0 },
  { id: "dermatology", name: "Dermatology", requested: 1, offered: 2, booked: 1, declined_full: 0, providers: 0, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "orthopaedics", name: "Orthopaedics", requested: 1, offered: 2, booked: 1, declined_full: 0, providers: 1, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "gynaecology", name: "Gynaecology", requested: 1, offered: 1, booked: 1, declined_full: 0, providers: 0, occupancy_pct: 100.0, extra_providers_needed: 0 },
  { id: "physiotherapy", name: "Physiotherapy", requested: 1, offered: 3, booked: 1, declined_full: 0, providers: 0, occupancy_pct: 33.3, extra_providers_needed: 0 },
];
export const MOCK_SERVICES_SUR = [
  { id: "general_practice", name: "General practice", requested: 3, offered: 3, booked: 2, declined_full: 0, providers: 1, occupancy_pct: 100.0, extra_providers_needed: 0 },
  { id: "paediatrics", name: "Paediatrics", requested: 1, offered: 2, booked: 1, declined_full: 0, providers: 0, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "dermatology", name: "Dermatology", requested: 1, offered: 1, booked: 1, declined_full: 0, providers: 0, occupancy_pct: 100.0, extra_providers_needed: 0 },
  { id: "orthopaedics", name: "Orthopaedics", requested: 1, offered: 2, booked: 0, declined_full: 0, providers: 0, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "gynaecology", name: "Gynaecology", requested: 0, offered: 1, booked: 0, declined_full: 0, providers: 0, occupancy_pct: 0.0, extra_providers_needed: 0 },
  { id: "physiotherapy", name: "Physiotherapy", requested: 0, offered: 1, booked: 0, declined_full: 0, providers: 0, occupancy_pct: 0.0, extra_providers_needed: 0 },
];

export const BAND_NAMES = ["Morning", "Midday", "Afternoon", "Evening"];

// weekday + one [demand, availability] pair per band -> a heatmap row. Kept
// as a helper so the three per-site grids below (and the network-wide one)
// stay readable instead of one giant object literal per weekday.
export function heatRow(weekday, pairs) {
  return {
    weekday,
    all_day_demand: 0,
    cells: BAND_NAMES.map((band, i) => ({ band, demand: pairs[i][0], availability: pairs[i][1] })),
  };
}

// Per-site grids, zeroed on the bands each site's own hours_label below
// says it is closed — demand_supply_heatmap() never mixes a site's numbers
// into another's, so these three (and their `open` matrices) must actually
// differ or the "Closed" cells and the site picker both look broken.
export const MOCK_HEATMAP_CENTRO = [
  heatRow("Monday", [[5, 4], [2, 2], [7, 3], [3, 1]]),
  heatRow("Tuesday", [[4, 4], [1, 2], [5, 4], [2, 0]]),
  heatRow("Wednesday", [[3, 3], [1, 2], [4, 5], [1, 1]]),
  heatRow("Thursday", [[4, 2], [2, 1], [9, 0], [4, 0]]),
  heatRow("Friday", [[5, 4], [1, 2], [5, 4], [0, 0]]),
  heatRow("Saturday", [[0, 0], [0, 0], [0, 0], [0, 0]]),
  heatRow("Sunday", [[0, 0], [0, 0], [0, 0], [0, 0]]),
];
export const MOCK_OPEN_CENTRO = [
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [false, false, false, false],
  [false, false, false, false],
];
export const MOCK_HEATMAP_NORTE = [
  heatRow("Monday", [[2, 1], [1, 1], [4, 2], [1, 1]]),
  heatRow("Tuesday", [[1, 1], [1, 1], [3, 2], [1, 0]]),
  heatRow("Wednesday", [[1, 1], [0, 1], [2, 2], [1, 0]]),
  heatRow("Thursday", [[2, 1], [1, 1], [4, 0], [2, 0]]),
  heatRow("Friday", [[3, 2], [1, 1], [2, 1], [0, 0]]),
  heatRow("Saturday", [[3, 2], [1, 1], [0, 0], [0, 0]]),
  heatRow("Sunday", [[0, 0], [0, 0], [0, 0], [0, 0]]),
];
export const MOCK_OPEN_NORTE = [
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [true, true, true, true],
  [true, true, false, false],
  [false, false, false, false],
];
export const MOCK_HEATMAP_SUR = [
  heatRow("Monday", [[1, 1], [0, 1], [0, 0], [0, 0]]),
  heatRow("Tuesday", [[1, 1], [0, 1], [0, 0], [0, 0]]),
  heatRow("Wednesday", [[1, 1], [0, 0], [0, 0], [0, 0]]),
  heatRow("Thursday", [[1, 1], [1, 0], [0, 0], [0, 0]]),
  heatRow("Friday", [[1, 1], [0, 0], [0, 0], [0, 0]]),
  heatRow("Saturday", [[0, 0], [0, 0], [0, 0], [0, 0]]),
  heatRow("Sunday", [[0, 0], [0, 0], [0, 0], [0, 0]]),
];
export const MOCK_OPEN_SUR = [
  [true, true, false, false],
  [true, true, false, false],
  [true, true, false, false],
  [true, true, false, false],
  [true, true, false, false],
  [false, false, false, false],
  [false, false, false, false],
];

export const MOCK_STATS = {
  calls_considered: 214,
  unavailability: MOCK_UNAVAILABILITY,
  cancellations: {
    ...MOCK_CANCELLATIONS,
    daily: [
      { date: "2026-09-15", freed: 3, relocated: 2, lost: 1 },
      { date: "2026-09-16", freed: 2, relocated: 1, lost: 0 },
      { date: "2026-09-17", freed: 1, relocated: 1, lost: 0 },
      { date: "2026-09-18", freed: 3, relocated: 2, lost: 1 },
      { date: "2026-09-19", freed: 2, relocated: 1, lost: 1 },
    ],
  },
  // Same shape business_insights.service_occupancy serves: one row per
  // specialty, network-wide ("all") and once per site.
  occupancy: {
    all: MOCK_SERVICES,
    sites: [
      { id: "centro", name: "Arenal Centro", services: MOCK_SERVICES_CENTRO },
      { id: "norte", name: "Arenal Norte", services: MOCK_SERVICES_NORTE },
      { id: "sur", name: "Arenal Sur", services: MOCK_SERVICES_SUR },
    ],
  },
  // Same shape business_insights.demand_supply_heatmap serves: 7 weekday
  // rows x the 4 bands, an `open` matrix per site for the "Closed" cells,
  // and `suggested_action` naming the hottest gap.
  heatmap: {
    bands: ["Morning", "Midday", "Afternoon", "Evening"],
    open: [
      [true, true, true, true],
      [true, true, true, true],
      [true, true, true, true],
      [true, true, true, true],
      [true, true, true, false],
      [true, true, false, false],
      [false, false, false, false],
    ],
    rows: [
      { weekday: "Monday", all_day_demand: 0, cells: [{ band: "Morning", demand: 8, availability: 6 }, { band: "Midday", demand: 3, availability: 4 }, { band: "Afternoon", demand: 12, availability: 5 }, { band: "Evening", demand: 4, availability: 2 }] },
      { weekday: "Tuesday", all_day_demand: 0, cells: [{ band: "Morning", demand: 6, availability: 6 }, { band: "Midday", demand: 2, availability: 4 }, { band: "Afternoon", demand: 9, availability: 7 }, { band: "Evening", demand: 3, availability: 0 }] },
      { weekday: "Wednesday", all_day_demand: 0, cells: [{ band: "Morning", demand: 5, availability: 5 }, { band: "Midday", demand: 1, availability: 3 }, { band: "Afternoon", demand: 7, availability: 8 }, { band: "Evening", demand: 2, availability: 1 }] },
      { weekday: "Thursday", all_day_demand: 0, cells: [{ band: "Morning", demand: 7, availability: 4 }, { band: "Midday", demand: 4, availability: 2 }, { band: "Afternoon", demand: 14, availability: 0 }, { band: "Evening", demand: 6, availability: 0 }] },
      { weekday: "Friday", all_day_demand: 0, cells: [{ band: "Morning", demand: 9, availability: 7 }, { band: "Midday", demand: 2, availability: 3 }, { band: "Afternoon", demand: 8, availability: 6 }, { band: "Evening", demand: 0, availability: 0 }] },
      { weekday: "Saturday", all_day_demand: 0, cells: [{ band: "Morning", demand: 4, availability: 3 }, { band: "Midday", demand: 1, availability: 1 }, { band: "Afternoon", demand: 0, availability: 0 }, { band: "Evening", demand: 0, availability: 0 }] },
      { weekday: "Sunday", all_day_demand: 0, cells: [{ band: "Morning", demand: 0, availability: 0 }, { band: "Midday", demand: 0, availability: 0 }, { band: "Afternoon", demand: 0, availability: 0 }, { band: "Evening", demand: 0, availability: 0 }] },
    ],
    sites: [
      { id: "centro", name: "Arenal Centro", hours_label: "Mon–Fri 09:00–20:00", open: MOCK_OPEN_CENTRO, rows: MOCK_HEATMAP_CENTRO },
      { id: "norte", name: "Arenal Norte", hours_label: "Mon–Fri 09:00–20:00 · Sat 09:00–14:00", open: MOCK_OPEN_NORTE, rows: MOCK_HEATMAP_NORTE },
      { id: "sur", name: "Arenal Sur", hours_label: "Mon–Fri 10:00–14:00", open: MOCK_OPEN_SUR, rows: MOCK_HEATMAP_SUR },
    ],
    suggested_action: "Thursday afternoons account for 14 appointment requests with only 0 slots offered in that band: opening up the schedule there would capture the largest pool of unmet demand.",
  },
};
