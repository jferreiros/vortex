// Deterministic matcher for the `match` rules on a patterns document
// (GET /api/wall/patterns).
// Input: a patient's events (+ optional referrals), a pattern, specialty, asOf date.
// Output: { matches: boolean, evidenceEventIds: string[] } — evidence is only
// real timeline events that the rule used (never condition nodes).

const MS_PER_DAY = 24 * 60 * 60 * 1000;

function parseDay(iso) {
  return new Date(`${iso}T00:00:00`);
}

function daysBetween(aIso, bIso) {
  return Math.round((parseDay(bIso) - parseDay(aIso)) / MS_PER_DAY);
}

function isVisit(e) {
  return e.shape?.family === "visit" && e.shape?.type !== "no-show";
}

function isBook(e) {
  // A successful book shows up as an outgoing appointment-suggestion that
  // led to a scheduled visit, or explicitly as a scheduling outcome. For the
  // mock timeline we treat: any subsequent visit OR an outgoing "appointment
  // suggestion" / "rebooking offer" after the reference as a book-like follow-up.
  // Real wiring will use submit action === "book".
  if (e.action === "book" || e.action === "reschedule") return true;
  const t = e.shape?.type;
  return e.shape?.family === "call" && (t === "appointment suggestion" || t === "rebooking offer");
}

function isIncomingCall(e) {
  return e.shape?.family === "call" && e.shape?.subfamily === "incoming";
}

function isCancellation(e) {
  return e.shape?.family === "call" && e.shape?.type === "cancellation";
}

function isNoAvailability(e) {
  return e.shape?.family === "call" && e.shape?.type === "no availability";
}

function filterSpecialty(events, specialty) {
  if (!specialty || specialty === "any") return events;
  return events.filter((e) => e.specialty === specialty);
}

function recallDaysFor(specialty, recallMap) {
  if (!recallMap) return 365;
  return recallMap[specialty] ?? recallMap.default ?? 365;
}

function countMatches(countRule, n) {
  if (!countRule) return true;
  if (countRule.eq != null && n !== countRule.eq) return false;
  if (countRule.min != null && n < countRule.min) return false;
  if (countRule.max != null && n > countRule.max) return false;
  return true;
}

/** Median interval (days) between consecutive visits; null if <2 visits. */
function visitIntervals(visits) {
  const intervals = [];
  for (let i = 1; i < visits.length; i += 1) {
    intervals.push(daysBetween(visits[i - 1].date, visits[i].date));
  }
  return intervals;
}

function isRegularCadence(intervals, tolerance = 0.35) {
  if (intervals.length === 0) return false;
  const mean = intervals.reduce((a, b) => a + b, 0) / intervals.length;
  if (mean <= 0) return false;
  return intervals.every((d) => Math.abs(d - mean) / mean <= tolerance);
}

function eventsAfter(events, dateIso) {
  return events.filter((e) => e.date > dateIso);
}

/**
 * @param {object} opts
 * @param {Array} opts.events - patient timeline events (sorted or unsorted)
 * @param {string[]} [opts.referrals] - open referral specialty ids
 * @param {object} opts.pattern - one entry from the patterns document
 * @param {string} opts.specialty - specialty under test (required when match.perSpecialty)
 * @param {string} opts.asOf - ISO date "today" for gap calculations
 * @param {object} opts.specialtyRecallDays - map from the patterns document
 */
export function evaluatePattern({ events, referrals = [], pattern, specialty, asOf, specialtyRecallDays }) {
  const rule = pattern.match;
  if (!rule || pattern.enabled === false) {
    return { matches: false, evidenceEventIds: [] };
  }

  const sorted = [...events].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const scoped = rule.perSpecialty === false ? sorted : filterSpecialty(sorted, specialty);
  const visits = scoped.filter(isVisit);
  const evidence = [];

  if (rule.visitCount && !countMatches(rule.visitCount, visits.length)) {
    return { matches: false, evidenceEventIds: [] };
  }

  if (rule.hasOpenReferral) {
    if (!specialty || !referrals.includes(specialty)) {
      return { matches: false, evidenceEventIds: [] };
    }
  }

  if (rule.noBookEver) {
    if (scoped.some(isBook) || visits.length > 0) {
      // visitCount eq 0 already checked; still block if any book-like event
      if (scoped.some(isBook)) return { matches: false, evidenceEventIds: [] };
    }
  }

  if (rule.hasCall) {
    const hit = scoped.find(
      (e) =>
        e.shape?.family === "call" &&
        e.shape?.type === rule.hasCall.type &&
        (!rule.hasCall.subfamily || e.shape?.subfamily === rule.hasCall.subfamily)
    );
    if (!hit) return { matches: false, evidenceEventIds: [] };
    evidence.push(hit.id);
  }

  if (rule.noBookSince === "last_cancellation") {
    const cancels = scoped.filter(isCancellation);
    if (cancels.length === 0) return { matches: false, evidenceEventIds: [] };
    const last = cancels[cancels.length - 1];
    if (!evidence.includes(last.id)) evidence.push(last.id);
    if (eventsAfter(scoped, last.date).some(isBook)) {
      return { matches: false, evidenceEventIds: [] };
    }
  }

  if (rule.noBookSinceLastVisit) {
    if (visits.length === 0) return { matches: false, evidenceEventIds: [] };
    const last = visits[visits.length - 1];
    if (eventsAfter(scoped, last.date).some(isBook)) {
      return { matches: false, evidenceEventIds: [] };
    }
  }

  if (rule.daysSinceLastVisit?.gtSpecialtyRecall) {
    if (visits.length === 0) return { matches: false, evidenceEventIds: [] };
    const last = visits[visits.length - 1];
    const need = recallDaysFor(specialty, specialtyRecallDays);
    if (daysBetween(last.date, asOf) <= need) {
      return { matches: false, evidenceEventIds: [] };
    }
    if (!evidence.includes(last.id)) evidence.push(last.id);
  }

  if (rule.visitsFormRegularCadence || rule.cadenceOverdue) {
    if (visits.length < 2) return { matches: false, evidenceEventIds: [] };
    const intervals = visitIntervals(visits);
    if (rule.visitsFormRegularCadence && !isRegularCadence(intervals)) {
      return { matches: false, evidenceEventIds: [] };
    }
    if (rule.cadenceOverdue) {
      const mean = intervals.reduce((a, b) => a + b, 0) / intervals.length;
      const last = visits[visits.length - 1];
      if (daysBetween(last.date, asOf) <= mean) {
        return { matches: false, evidenceEventIds: [] };
      }
    }
    visits.forEach((v) => {
      if (!evidence.includes(v.id)) evidence.push(v.id);
    });
  }

  // first-visit evidence: the single visit (even when gap/noBook already checked)
  if (rule.visitCount?.eq === 1 && visits.length === 1) {
    if (!evidence.includes(visits[0].id)) evidence.push(visits[0].id);
  }

  if (rule.noCallOrVisitSince) {
    const { ref, withinDays } = rule.noCallOrVisitSince;
    let anchor = null;
    if (ref === "last_no_availability") {
      const hits = scoped.filter(isNoAvailability);
      if (hits.length === 0) return { matches: false, evidenceEventIds: [] };
      anchor = hits[hits.length - 1];
    }
    if (!anchor) return { matches: false, evidenceEventIds: [] };
    if (!evidence.includes(anchor.id)) evidence.push(anchor.id);
    const since = eventsAfter(scoped, anchor.date);
    const recovered = since.some((e) => isVisit(e) || isIncomingCall(e) || e.shape?.family === "call");
    if (recovered) return { matches: false, evidenceEventIds: [] };
    if (daysBetween(anchor.date, asOf) > withinDays) {
      // Still unrecovered after the window — match (waitlist offer).
    } else {
      // Inside the window and unrecovered — also match (still waiting).
    }
  }

  if (rule.incomingCallCount) {
    const { min, withinDays } = rule.incomingCallCount;
    const incoming = (rule.perSpecialty === false ? sorted : scoped).filter(isIncomingCall);
    // Find any window of `withinDays` containing >= min incoming calls
    let windowHits = [];
    for (let i = 0; i < incoming.length; i += 1) {
      const start = incoming[i];
      const group = incoming.filter(
        (c) => c.date >= start.date && daysBetween(start.date, c.date) <= withinDays
      );
      if (group.length >= min) {
        windowHits = group;
        break;
      }
    }
    if (windowHits.length < min) return { matches: false, evidenceEventIds: [] };

    if (rule.noSuccessfulBookInWindow) {
      const from = windowHits[0].date;
      const to = windowHits[windowHits.length - 1].date;
      const inWindow = sorted.filter((e) => e.date >= from && e.date <= to);
      if (inWindow.some((e) => e.action === "book" || isBook(e))) {
        // Outgoing suggestion alone shouldn't count as successful book for this rule —
        // only an explicit book action or a visit that resulted from it.
        if (inWindow.some((e) => e.action === "book" || isVisit(e))) {
          return { matches: false, evidenceEventIds: [] };
        }
      }
    }
    windowHits.forEach((c) => {
      if (!evidence.includes(c.id)) evidence.push(c.id);
    });
  }

  // unfulfilled-referral: no real events — evidence stays empty (conditions only)
  if (rule.hasOpenReferral && rule.visitCount?.eq === 0) {
    return { matches: true, evidenceEventIds: [] };
  }

  return { matches: true, evidenceEventIds: evidence };
}

/**
 * Pick the first enabled matching pattern for a patient in a specialty
 * (or across specialties when the rule is not perSpecialty).
 */
export function findMatchingPattern({
  events,
  referrals = [],
  patterns,
  specialty,
  asOf,
  specialtyRecallDays,
}) {
  const enabled = patterns.filter((p) => p.enabled !== false);
  const specialties =
    specialty && specialty !== "any"
      ? [specialty]
      : [...new Set(events.map((e) => e.specialty).filter(Boolean))];

  for (const pattern of enabled) {
    if (pattern.match?.perSpecialty === false) {
      const result = evaluatePattern({
        events,
        referrals,
        pattern,
        specialty: null,
        asOf,
        specialtyRecallDays,
      });
      if (result.matches) {
        return { pattern, specialty: null, evidenceEventIds: result.evidenceEventIds };
      }
      continue;
    }

    const tryList = specialties.length ? specialties : [specialty].filter(Boolean);
    for (const spec of tryList) {
      const result = evaluatePattern({
        events,
        referrals,
        pattern,
        specialty: spec,
        asOf,
        specialtyRecallDays,
      });
      if (result.matches) {
        return { pattern, specialty: spec, evidenceEventIds: result.evidenceEventIds };
      }
    }
  }

  return null;
}
