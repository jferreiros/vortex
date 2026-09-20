
// Placeholder numbers for the panels whose real endpoint is not wired yet.
// Everything the board already serves (Home, live calls, business insights)
// reads its own API; these are the leftovers, kept together so the next
// endpoint to land can delete its block outright.
export const MOCK_UNAVAILABILITY = {
  unmet_total: 19,
  buckets: [
    { key: "no_slot_in_window", label: "Sin hueco en la franja pedida", count: 9, share: 1, pct: 47.4 },
    { key: "provider_unavailable", label: "Médico concreto no disponible", count: 5, share: 0.556, pct: 26.3 },
    { key: "policy_not_covered", label: "Póliza no cubierta", count: 3, share: 0.333, pct: 15.8 },
    { key: "out_of_hours", label: "Fuera de horario", count: 2, share: 0.222, pct: 10.5 },
  ],
  suggested_action:
    "El 47% de la demanda no cubierta es por falta de hueco en la franja pedida, concentrado los jueves en la tarde: ampliar agenda ese tramo capturaría la mayor parte de esos rechazos.",
};

export const MOCK_CANCELLATIONS = {
  freed_total: 11,
  relocated: 7,
  lost: 3,
  pending: 1,
  recovery_rate_pct: 70,
  suggested_action:
    "De los 11 huecos liberados por cancelación, 7 se reubicaron (70%) pero 3 llegaron vacíos el día de la cita: avisar a la lista de espera en el instante de la cancelación recuperaría parte de esos huecos.",
};

// One mock row per catalogue specialty — the six Arenal services, network-wide.
export const MOCK_SERVICES = [
  { id: "general_practice", name: "Medicina general", requested: 21, offered: 18, booked: 15, declined_full: 3, providers: 3, occupancy_pct: 116.7, extra_providers_needed: 1 },
  { id: "paediatrics", name: "Pediatría", requested: 9, offered: 12, booked: 8, declined_full: 0, providers: 2, occupancy_pct: 75.0, extra_providers_needed: 0 },
  { id: "dermatology", name: "Dermatología", requested: 6, offered: 8, booked: 5, declined_full: 0, providers: 1, occupancy_pct: 75.0, extra_providers_needed: 0 },
  { id: "orthopaedics", name: "Traumatología", requested: 5, offered: 10, booked: 4, declined_full: 0, providers: 2, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "gynaecology", name: "Ginecología", requested: 3, offered: 6, booked: 3, declined_full: 0, providers: 1, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "physiotherapy", name: "Fisioterapia", requested: 2, offered: 9, booked: 2, declined_full: 0, providers: 1, occupancy_pct: 22.2, extra_providers_needed: 0 },
];

// Per-site mock rows, distinct from each other and from the network-wide
// total above — the real service_occupancy() scopes every count to one
// site's own find_slots calls, so these three must actually differ or the
// site picker looks broken even when the wiring is correct.
export const MOCK_SERVICES_CENTRO = [
  { id: "general_practice", name: "Medicina general", requested: 12, offered: 10, booked: 9, declined_full: 2, providers: 2, occupancy_pct: 120.0, extra_providers_needed: 1 },
  { id: "paediatrics", name: "Pediatría", requested: 5, offered: 6, booked: 4, declined_full: 0, providers: 1, occupancy_pct: 83.3, extra_providers_needed: 0 },
  { id: "dermatology", name: "Dermatología", requested: 4, offered: 5, booked: 3, declined_full: 0, providers: 1, occupancy_pct: 80.0, extra_providers_needed: 0 },
  { id: "orthopaedics", name: "Traumatología", requested: 3, offered: 6, booked: 3, declined_full: 0, providers: 1, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "gynaecology", name: "Ginecología", requested: 2, offered: 4, booked: 2, declined_full: 0, providers: 1, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "physiotherapy", name: "Fisioterapia", requested: 1, offered: 5, booked: 1, declined_full: 0, providers: 1, occupancy_pct: 20.0, extra_providers_needed: 0 },
];
export const MOCK_SERVICES_NORTE = [
  { id: "general_practice", name: "Medicina general", requested: 6, offered: 5, booked: 4, declined_full: 1, providers: 1, occupancy_pct: 120.0, extra_providers_needed: 1 },
  { id: "paediatrics", name: "Pediatría", requested: 3, offered: 4, booked: 3, declined_full: 0, providers: 1, occupancy_pct: 75.0, extra_providers_needed: 0 },
  { id: "dermatology", name: "Dermatología", requested: 1, offered: 2, booked: 1, declined_full: 0, providers: 0, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "orthopaedics", name: "Traumatología", requested: 1, offered: 2, booked: 1, declined_full: 0, providers: 1, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "gynaecology", name: "Ginecología", requested: 1, offered: 1, booked: 1, declined_full: 0, providers: 0, occupancy_pct: 100.0, extra_providers_needed: 0 },
  { id: "physiotherapy", name: "Fisioterapia", requested: 1, offered: 3, booked: 1, declined_full: 0, providers: 0, occupancy_pct: 33.3, extra_providers_needed: 0 },
];
export const MOCK_SERVICES_SUR = [
  { id: "general_practice", name: "Medicina general", requested: 3, offered: 3, booked: 2, declined_full: 0, providers: 1, occupancy_pct: 100.0, extra_providers_needed: 0 },
  { id: "paediatrics", name: "Pediatría", requested: 1, offered: 2, booked: 1, declined_full: 0, providers: 0, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "dermatology", name: "Dermatología", requested: 1, offered: 1, booked: 1, declined_full: 0, providers: 0, occupancy_pct: 100.0, extra_providers_needed: 0 },
  { id: "orthopaedics", name: "Traumatología", requested: 1, offered: 2, booked: 0, declined_full: 0, providers: 0, occupancy_pct: 50.0, extra_providers_needed: 0 },
  { id: "gynaecology", name: "Ginecología", requested: 0, offered: 1, booked: 0, declined_full: 0, providers: 0, occupancy_pct: 0.0, extra_providers_needed: 0 },
  { id: "physiotherapy", name: "Fisioterapia", requested: 0, offered: 1, booked: 0, declined_full: 0, providers: 0, occupancy_pct: 0.0, extra_providers_needed: 0 },
];

export const BAND_NAMES = ["Mañana", "Mediodía", "Tarde", "Tarde-noche"];

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
// differ or the "Cerrado" cells and the site picker both look broken.
export const MOCK_HEATMAP_CENTRO = [
  heatRow("Lunes", [[5, 4], [2, 2], [7, 3], [3, 1]]),
  heatRow("Martes", [[4, 4], [1, 2], [5, 4], [2, 0]]),
  heatRow("Miércoles", [[3, 3], [1, 2], [4, 5], [1, 1]]),
  heatRow("Jueves", [[4, 2], [2, 1], [9, 0], [4, 0]]),
  heatRow("Viernes", [[5, 4], [1, 2], [5, 4], [0, 0]]),
  heatRow("Sábado", [[0, 0], [0, 0], [0, 0], [0, 0]]),
  heatRow("Domingo", [[0, 0], [0, 0], [0, 0], [0, 0]]),
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
  heatRow("Lunes", [[2, 1], [1, 1], [4, 2], [1, 1]]),
  heatRow("Martes", [[1, 1], [1, 1], [3, 2], [1, 0]]),
  heatRow("Miércoles", [[1, 1], [0, 1], [2, 2], [1, 0]]),
  heatRow("Jueves", [[2, 1], [1, 1], [4, 0], [2, 0]]),
  heatRow("Viernes", [[3, 2], [1, 1], [2, 1], [0, 0]]),
  heatRow("Sábado", [[3, 2], [1, 1], [0, 0], [0, 0]]),
  heatRow("Domingo", [[0, 0], [0, 0], [0, 0], [0, 0]]),
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
  heatRow("Lunes", [[1, 1], [0, 1], [0, 0], [0, 0]]),
  heatRow("Martes", [[1, 1], [0, 1], [0, 0], [0, 0]]),
  heatRow("Miércoles", [[1, 1], [0, 0], [0, 0], [0, 0]]),
  heatRow("Jueves", [[1, 1], [1, 0], [0, 0], [0, 0]]),
  heatRow("Viernes", [[1, 1], [0, 0], [0, 0], [0, 0]]),
  heatRow("Sábado", [[0, 0], [0, 0], [0, 0], [0, 0]]),
  heatRow("Domingo", [[0, 0], [0, 0], [0, 0], [0, 0]]),
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
  // rows x the 4 bands, an `open` matrix per site for the "Cerrado" cells,
  // and `suggested_action` naming the hottest gap.
  heatmap: {
    bands: ["Mañana", "Mediodía", "Tarde", "Tarde-noche"],
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
      { weekday: "Lunes", all_day_demand: 0, cells: [{ band: "Mañana", demand: 8, availability: 6 }, { band: "Mediodía", demand: 3, availability: 4 }, { band: "Tarde", demand: 12, availability: 5 }, { band: "Tarde-noche", demand: 4, availability: 2 }] },
      { weekday: "Martes", all_day_demand: 0, cells: [{ band: "Mañana", demand: 6, availability: 6 }, { band: "Mediodía", demand: 2, availability: 4 }, { band: "Tarde", demand: 9, availability: 7 }, { band: "Tarde-noche", demand: 3, availability: 0 }] },
      { weekday: "Miércoles", all_day_demand: 0, cells: [{ band: "Mañana", demand: 5, availability: 5 }, { band: "Mediodía", demand: 1, availability: 3 }, { band: "Tarde", demand: 7, availability: 8 }, { band: "Tarde-noche", demand: 2, availability: 1 }] },
      { weekday: "Jueves", all_day_demand: 0, cells: [{ band: "Mañana", demand: 7, availability: 4 }, { band: "Mediodía", demand: 4, availability: 2 }, { band: "Tarde", demand: 14, availability: 0 }, { band: "Tarde-noche", demand: 6, availability: 0 }] },
      { weekday: "Viernes", all_day_demand: 0, cells: [{ band: "Mañana", demand: 9, availability: 7 }, { band: "Mediodía", demand: 2, availability: 3 }, { band: "Tarde", demand: 8, availability: 6 }, { band: "Tarde-noche", demand: 0, availability: 0 }] },
      { weekday: "Sábado", all_day_demand: 0, cells: [{ band: "Mañana", demand: 4, availability: 3 }, { band: "Mediodía", demand: 1, availability: 1 }, { band: "Tarde", demand: 0, availability: 0 }, { band: "Tarde-noche", demand: 0, availability: 0 }] },
      { weekday: "Domingo", all_day_demand: 0, cells: [{ band: "Mañana", demand: 0, availability: 0 }, { band: "Mediodía", demand: 0, availability: 0 }, { band: "Tarde", demand: 0, availability: 0 }, { band: "Tarde-noche", demand: 0, availability: 0 }] },
    ],
    sites: [
      { id: "centro", name: "Arenal Centro", hours_label: "L–V 09:00–20:00", open: MOCK_OPEN_CENTRO, rows: MOCK_HEATMAP_CENTRO },
      { id: "norte", name: "Arenal Norte", hours_label: "L–V 09:00–20:00 · S 09:00–14:00", open: MOCK_OPEN_NORTE, rows: MOCK_HEATMAP_NORTE },
      { id: "sur", name: "Arenal Sur", hours_label: "L–V 10:00–14:00", open: MOCK_OPEN_SUR, rows: MOCK_HEATMAP_SUR },
    ],
    suggested_action: "Los jueves en la franja de tarde concentran 14 peticiones de cita con solo 0 huecos ofrecidos ese tramo: abrir agenda ahí capturaría la mayor bolsa de demanda sin horario.",
  },
};
