// PLACEHOLDER DATA — every generator here is deterministic (seeded), not
// random-per-render, so the dashboard doesn't jitter on re-render or
// filter round-trips. Swap these for real aggregation endpoints later;
// the chart components below don't need to change shape.

export const SITES = ["Arenal Centro", "Arenal Norte", "Arenal Sur"];
export const SPECIALTIES = [
  "Medicina general",
  "Pediatría",
  "Dermatología",
  "Traumatología",
  "Ginecología",
];

const DAY_LABEL = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];

function mulberry32(seed) {
  let a = seed;
  return function rand() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashSeed(text) {
  let h = 0;
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h || 1;
}

const BUSINESS_HOURS = [8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20];

// One stacked bar per open hour: booking / rescheduling / cancelling.
export function hourlyActionVolume() {
  const rand = mulberry32(hashSeed("hourly-volume"));
  return BUSINESS_HOURS.map((hour) => {
    const base = 3 + rand() * 9;
    const booking = Math.round(base * (0.55 + rand() * 0.15));
    const reschedule = Math.round(base * (0.2 + rand() * 0.12));
    const cancel = Math.round(base * (0.1 + rand() * 0.1));
    return { hour, booking, reschedule, cancel };
  });
}

// Total call volume, one point per day, for every day mock data exists —
// a real endpoint would return however many days it has; this fakes 24.
export function dailyCallVolume(days = 24) {
  const rand = mulberry32(hashSeed("daily-volume"));
  const today = new Date();
  const out = [];
  let level = 34;
  for (let i = days - 1; i >= 0; i -= 1) {
    level += (rand() - 0.5) * 8;
    level = Math.max(18, Math.min(58, level));
    const date = new Date(today);
    date.setDate(date.getDate() - i);
    out.push({ date, total: Math.round(level) });
  }
  return out;
}

// Occupancy: a 7-day mini calendar + an upcoming-month total, both a
// function of the (site, specialty) filter so switching filters visibly
// changes the numbers, same as a real query would.
export function occupancy({ site, specialty } = {}) {
  const key = `occupancy:${site || "all"}:${specialty || "all"}`;
  const rand = mulberry32(hashSeed(key));
  const today = new Date();
  const centerPct = 38 + rand() * 30;

  const week = Array.from({ length: 7 }, (_, i) => {
    const date = new Date(today);
    date.setDate(date.getDate() + i);
    const pct = Math.max(4, Math.min(96, Math.round(centerPct + (rand() - 0.5) * 34)));
    return { date, label: DAY_LABEL[date.getDay()], pct };
  });

  const weekAvgPct = Math.round(week.reduce((sum, d) => sum + d.pct, 0) / week.length);
  const monthPct = Math.max(4, Math.min(96, Math.round(centerPct + (rand() - 0.5) * 14)));

  return { week, weekAvgPct, monthPct };
}

export function newClientsRegistered() {
  const rand = mulberry32(hashSeed("new-clients"));
  return Math.round(8 + rand() * 14);
}
