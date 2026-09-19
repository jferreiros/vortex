"""rules/ tools - what the clinic does not do.

Owner: the rules lane. Problems 6 (the rules), 10 (triage), 15 (the nearest
site), 16 (the questions) and 17 (the second policy).

The one thing every tool here owes the rest of the pipeline is the *right*
``reason``. The value a tool returns is the value we submit, and it has to name
the rule that actually stopped the booking, not a plausible one. That is why
the first eleven values of the closed vocabulary mirror the clinic's own
restrictions one for one: whatever bit, there is a value for it.

Where each answer comes from:

- ``check_eligibility`` reads ``/availability``'s ``blocked`` for anything about
  a particular doctor and for the two plan rules ``/clinic`` never publishes
  (its own referral, its yearly allowance), and derives the rest from the
  catalogue records themselves (see ``rules/eligibility.py``). It never
  guesses: every refusal is a field on a published record or a restriction id
  the platform named.
- ``triage`` is a lookup on the published symptom table (``rules/triage.py``).
  Red flags escalate and book nothing.
- ``nearest_location`` measures straight-line distance to the published
  coordinates, among the sites that can serve the request (``rules/geo.py``).
- ``find_provider`` matches a spoken name against the catalogue, and reports
  the near-miss pairs as ambiguous rather than picking one.
- ``clinic_facts`` answers the caller's questions about the clinic itself -
  which site opens on a Saturday, who sits at Norte, is there a site in Getafe
  - off the catalogue (``rules/facts.py``). The caller books on the answer, so
  it is never given from memory.

A refusal carrying one of the five *insurance* reasons is the signal for
problem 17: the plan on file will not cover this, and the caller may hold a
second one that does. It is not in the API — the only way to find it is to ask
on the call, and then to call ``check_eligibility`` again with ``insurer`` set
to what they said. ``INSURANCE_REASONS`` below is that set.
"""

from __future__ import annotations

import unicodedata
from datetime import timedelta
from difflib import SequenceMatcher

from vortex.contract import (
    MADRID,
    RULE_REASONS,
    AvailabilityResponse,
    BlockedProvider,
    Catalogue,
    CheckEligibilityInput,
    ClinicFacts,
    ClinicFactsInput,
    DeclineReason,
    EligibilityVerdict,
    FindProviderInput,
    NearestLocationInput,
    NearestLocationResult,
    PatientRecord,
    ProviderMatch,
    Rejection,
    SkippedEligibilityCheck,
    ToolContext,
    TriageInput,
    TriageResult,
    recall_patient,
    remember_patient,
)
from vortex.identity import tools as identity
from vortex.rules import eligibility, facts, geo
from vortex.rules import triage as triage_table
from vortex.settings import Settings

_TITLES = {"dr", "dra", "d", "doctor", "doctora"}
_TYPO_MATCH_CUTOFF = 0.8

#: How far ahead ``check_eligibility`` asks /availability about. The API caps a
#: span at 14 days, and a rule that bites bites on every day of the window.
_ELIGIBILITY_WINDOW_DAYS = 13

#: The five refusals that are about the plan, not about the clinic. Any of them
#: is the cue to ask the caller whether they hold other cover (problem 17).
INSURANCE_REASONS: frozenset[str] = frozenset(
    {
        "specialty_not_covered",
        "location_not_covered",
        "provider_not_in_network",
        "insurer_referral_required",
        "allowance_exhausted",
    }
)

#: The two of them that stop the plan, not a doctor. ``/availability`` names
#: them on whichever provider it was asked about, but no other provider in the
#: specialty escapes them, so there is nobody to redirect to.
_PLAN_WIDE_REASONS: frozenset[str] = frozenset({"insurer_referral_required", "allowance_exhausted"})


def _settings_of(ctx: ToolContext) -> Settings:
    """The socket's Settings. ``CallSession.open`` attaches them; bare tests stay offline."""
    settings = getattr(ctx, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return Settings(geocoder="", geocoder_url="")


def _name_tokens(name: str) -> set[str]:
    """Lower-cased, accent-folded, title-stripped tokens — for surname matching."""
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    tokens = {t.strip(".,").lower() for t in folded.split()}
    return tokens - _TITLES


def _fuzzy_subset(wanted: set[str], have: set[str]) -> bool:
    """Every spoken token fuzzy-matches one of the provider's — for a mis-heard name."""
    return all(
        any(SequenceMatcher(None, w, h).ratio() >= _TYPO_MATCH_CUTOFF for h in have) for w in wanted
    )


def _providers_named(catalogue: Catalogue, spoken_name: str, specialty_id: str | None) -> list:
    """Everyone in the catalogue the spoken name can mean, within a specialty if given.

    Every token the caller said (surname alone is enough) must be one of the
    provider's tokens — deterministic, and never confuses Sáez with Sáenz,
    since "saez" and "saenz" are different tokens even after accent-folding.
    Only when nothing matches at all is the mis-heard-name fallback tried.
    """
    pool = catalogue.providers
    if specialty_id:
        pool = [p for p in pool if p.specialty_id == specialty_id]
    target = _name_tokens(spoken_name)
    if not target:
        return []
    matches = [p for p in pool if target <= _name_tokens(p.name)]
    if not matches:
        matches = [p for p in pool if _fuzzy_subset(target, _name_tokens(p.name))]
    return matches


#: Ids this call has already failed to place, so one miss costs one query and
#: not one per rule. Per call, like everything on ``ToolContext``.
PATIENT_MISSES_KEY = "rules.patient_misses"

#: Patient-record rules that stand down when the directory record is missing.
#: The refusal, if there is one, still comes from ``/availability``; this says
#: which local checks did not get a chance to speak. A tuple, so no importer can
#: edit what every later call then copies into its verdict.
NO_RECORD_SKIPPED: tuple[SkippedEligibilityCheck, ...] = ("age", "referral")


async def _patient(ctx: ToolContext, patient_id: str) -> PatientRecord | None:
    """The directory record behind a ``patient_id``. Age and referrals live on it.

    ``GET /api/v1/directory`` takes ``name``, ``national_id``, ``phone`` or
    ``date_of_birth`` and nothing else: there is no lookup by id, and a
    parameter-less call is a ``422``, not the whole directory. So the record is
    got from a query somebody already made — identity's ``find_patient``, which
    every call runs before there is a ``patient_id`` to pass here at all, and
    which stashes what it fetched on the context.

    Failing that (a tool called cold, an id from somewhere else), the one query
    this lane can build from call context alone is the number that dialled in.
    It is exact, so a hit is the record for *this* id or nothing.

    ``None`` is safe, never fatal: the rules read off the record stand down and
    ``/availability?patient_id=`` answers on its own — it applies the same age
    and referral rules server-side and names them in ``blocked``. It is logged
    and listed on ``skipped_checks`` so a stood-down rule is visible, not silent.
    """
    record = recall_patient(ctx, patient_id)
    if record is not None:
        return record

    misses: list[str] = ctx.state.setdefault(PATIENT_MISSES_KEY, [])
    if patient_id not in misses and ctx.from_number:
        try:
            for match in await ctx.clinic.directory(phone=ctx.from_number):
                remember_patient(ctx, match)
        except Exception as exc:  # a directory hiccup must not lose the call
            ctx.log.event("rules.patient_lookup_failed", patient_id=patient_id, error=str(exc))
        record = recall_patient(ctx, patient_id)

    if record is None:
        if patient_id not in misses:
            misses.append(patient_id)
        ctx.log.event(
            "rules.patient_missing",
            patient_id=patient_id,
            searched_phone=bool(ctx.from_number),
        )
    return record


def _blocked_reason(
    availability: AvailabilityResponse, provider_id: str | None
) -> BlockedProvider | None:
    """What ``/availability`` says stopped this request, if it says anything.

    With a doctor named, only that doctor's entry answers. Without one, a
    blocked list and no slots at all means every candidate was stopped, and the
    first rule named is the rule to report.
    """
    if not availability.blocked:
        return None
    if provider_id:
        return next((b for b in availability.blocked if b.provider_id == provider_id), None)
    if availability.slots:
        return None
    ruled = [b for b in availability.blocked if b.reason in RULE_REASONS]
    return (ruled or availability.blocked)[0]


def _redirect(
    catalogue: Catalogue,
    args: CheckEligibilityInput,
    availability: AvailabilityResponse,
    blocked: BlockedProvider,
    plan,
) -> list:
    """Who else could take the request the blocked provider cannot.

    Everyone ``/availability`` stopped is out, not only the one reported: a
    plan rule (its own referral, its allowance) stops every candidate at once,
    and a redirect list naming them would send the caller to the same refusal.
    """
    if blocked.reason in _PLAN_WIDE_REASONS:
        return []
    blocked_ids = {args.provider_id} if args.provider_id else set()
    blocked_ids.add(blocked.provider_id)
    blocked_ids.update(b.provider_id for b in availability.blocked)
    specialty = args.specialty_id
    if not specialty:
        named = next((p for p in catalogue.providers if p.provider_id == blocked.provider_id), None)
        specialty = named.specialty_id if named else None
    return eligibility.providers_for(
        catalogue,
        specialty,
        location_id=args.location_id,
        plan=plan,
        exclude=blocked_ids,
    )


def _refuse(reason: DeclineReason, detail: str, redirect_to=None) -> EligibilityVerdict:
    return EligibilityVerdict(
        allowed=False,
        rejection=Rejection(reason=reason, detail=detail),
        redirect_to=redirect_to or [],
    )


def _noted(
    verdict: EligibilityVerdict,
    note: str = "",
    skipped_checks: list[SkippedEligibilityCheck] | None = None,
) -> EligibilityVerdict:
    """Carry resolution hints and stood-down checks out to the caller."""
    updates: dict = {}
    if note:
        updates["note"] = note
    if skipped_checks:
        updates["skipped_checks"] = list(skipped_checks)
    return verdict.model_copy(update=updates) if updates else verdict


async def check_eligibility(ctx: ToolContext, args: CheckEligibilityInput) -> EligibilityVerdict:
    """Can this patient book this specialty/provider/site under this plan?

    The order is the order the clinic hits the rules in, and it decides which
    reason gets submitted when more than one is true:

    1. **The patient's own rules** — age, the specialty's referral, and what the
       plan covers. These are plain fields on the catalogue and directory
       records, so they can be read rather than guessed, and they are the
       widest: an under-14 asking for general practice is an age refusal
       whatever their insurer says.
    2. **What /availability says** in ``blocked``. The live API is the authority
       on its own doctors, so its wording wins for anything provider-shaped.
       It is also the *only* source for the two plan rules the catalogue has no
       field for, ``insurer_referral_required`` and ``allowance_exhausted``:
       the restriction id is submitted as-is, never derived.
    3. **The provider's own rules**, derived, for when the API did not answer —
       offline, or a request too vague for it to refuse.
    4. Slots, or ``no_availability`` when the calendar is simply full.

    ``insurer`` is the plan to quote against. Left empty it is the one plan the
    record carries; the second policy of problem 17 reaches this tool only by
    being named here, because it exists nowhere in the API.
    """
    today = ctx.now.astimezone(MADRID).date()
    catalogue = await ctx.clinic.catalogue()
    patient = await _patient(ctx, args.patient_id)
    # A missing record is not a refusal — it is a verdict with stood-down checks,
    # and every answer below carries them rather than passing quietly.
    skipped: list[SkippedEligibilityCheck] = [] if patient else list(NO_RECORD_SKIPPED)
    note = ""
    # The second policy of problem 17 arrives as whatever the caller said aloud
    # ("Mapfre Salud", "Nueva Mutua Sanitaria"), never as the bare id the
    # platform submits against. Resolve it the same way registration does, so
    # a plan named by its full name is not mistaken for an unknown one — and
    # tell the caller-facing side which id to reuse for find_slots/policy_id,
    # since nothing downstream re-derives it from what was said here.
    resolved_insurer = identity.resolve_insurer(args.insurer, catalogue) if args.insurer else None
    plan = eligibility.resolve_plan(catalogue, patient, resolved_insurer or args.insurer)
    if (
        plan is not None
        and args.insurer
        and plan.insurer_id.lower() != args.insurer.strip().lower()
    ):
        note = f"'{args.insurer}' is {plan.name}; use insurer/policy_id {plan.insurer_id!r} onward"

    verdict = eligibility.check_patient_rules(
        catalogue,
        patient,
        specialty_id=args.specialty_id,
        location_id=args.location_id,
        plan=plan,
        today=today,
    )
    if verdict:
        return _noted(
            _refuse(verdict.reason, verdict.detail, verdict.redirect_to),
            note,
            skipped,
        )

    availability = await ctx.clinic.availability(
        date_from=today + timedelta(days=1),
        date_to=today + timedelta(days=_ELIGIBILITY_WINDOW_DAYS),
        provider_id=args.provider_id,
        specialty_id=args.specialty_id,
        location_id=args.location_id,
        patient_id=args.patient_id,
        insurer=[plan.insurer_id] if plan else None,
    )

    blocked = _blocked_reason(availability, args.provider_id)
    if blocked is not None:
        return _noted(
            _refuse(
                blocked.reason,
                blocked.detail or "the clinic's availability named this rule",
                _redirect(catalogue, args, availability, blocked, plan),
            ),
            note,
            skipped,
        )

    provider = next((p for p in catalogue.providers if p.provider_id == args.provider_id), None)
    verdict = eligibility.check_provider_rules(
        catalogue,
        provider,
        specialty_id=args.specialty_id,
        location_id=args.location_id,
        plan=plan,
        today=today,
    )
    if verdict:
        return _noted(
            _refuse(verdict.reason, verdict.detail, verdict.redirect_to),
            note,
            skipped,
        )

    if availability.slots:
        return _noted(EligibilityVerdict(allowed=True), note, skipped)
    return _noted(
        _refuse("no_availability", "nothing free in the window the clinic offers"),
        note,
        skipped,
    )


async def triage(ctx: ToolContext, args: TriageInput) -> TriageResult:
    """Symptom -> specialty, or emergency.

    A lookup on the table problem 10 publishes, never a clinical judgement. The
    five red flags are checked first and book nothing: they return no specialty
    at all, so there is no agenda for the call to fall back onto.

    A doctor the caller named outranks the table. General practice is the
    table's residue for anything it does not recognise, and booking it for a
    caller who asked for Dr. Iglesia sends an orthopaedic wrist to a GP. So
    when ``provider_name`` resolves in the catalogue, the specialty is the one
    that doctor actually consults in — the only specialty they can be booked
    for. The complaint answers alone when the name resolves to nobody, or to
    people in more than one specialty (Sáez/Sáenz), which the table can split.

    A specialty the caller named outranks the table for the same reason. The
    table holds symptoms, so it scores nothing for the word "gynaecology" and
    sends a caller who asked for it to the residue — which is the wrong agenda,
    the wrong ``appointment_type_id`` and a lost case. A child marker still wins
    over a named specialty: nothing published sends a child anywhere but
    paediatrics, and the age rule agrees.

    Where the table recognises nothing in ``complaint``, the caller's own turns
    are read for that name instead. The model paraphrases the complaint down to
    the symptom — "I need a dermatology appointment, about a mole on my back"
    arrives as the mole alone in every one of the six live calls that said it —
    and the residue it lands on is a guess made from no evidence at all. A
    complaint the table *did* recognise is answered by the table, so a specialty
    the caller only mentioned in passing never outranks a symptom that scored.
    """
    flag = triage_table.red_flag(args.complaint)
    if flag:
        ctx.log.event("triage.red_flag", flag=flag, complaint=args.complaint)
        return TriageResult(
            specialty_id=None,
            emergency=True,
            rejection=Rejection(reason="medical_emergency", detail=f"published red flag: {flag}"),
        )

    routed = triage_table.route(args.complaint)
    if args.provider_name:
        catalogue = await ctx.clinic.catalogue()
        named = _providers_named(catalogue, args.provider_name, None)
        specialties = {p.specialty_id for p in named}
        if len(specialties) == 1:
            specialty_id = named[0].specialty_id
            assert specialty_id, "a catalogue provider always carries a specialty"
            if specialty_id != routed:
                ctx.log.event(
                    "triage.specialty_from_provider",
                    provider_name=args.provider_name,
                    specialty_id=specialty_id,
                    table_said=routed,
                )
            return TriageResult(
                specialty_id=specialty_id,
                emergency=False,
                provider_id=named[0].provider_id if len(named) == 1 else None,
            )
        ctx.log.event(
            "triage.provider_unresolved",
            provider_name=args.provider_name,
            candidates=len(named),
            specialty_id=routed,
        )

    said = args.complaint
    asked_for = triage_table.named_specialty(said)
    if asked_for is None and not triage_table.score(said):
        # The table matched nothing at all, so general practice here is a guess
        # made from no evidence. The caller's own turns are better evidence than
        # a summary of them: "I need a dermatology appointment, about a mole on
        # my back" reaches this tool as the mole alone, six times out of six in
        # the live log. Only read them in this branch - a complaint the table
        # did recognise is answered by the table, and a specialty mentioned in
        # passing must never outrank a symptom that scored. The child guard
        # below then reads the same words the specialty came out of.
        said = ctx.log.caller_words()
        asked_for = triage_table.named_specialty(said)

    if asked_for and asked_for != routed and not triage_table.mentions_child(said):
        ctx.log.event(
            "triage.specialty_named_by_caller",
            complaint=args.complaint,
            specialty_id=asked_for,
            table_said=routed,
            from_transcript=said is not args.complaint,
        )
        return TriageResult(specialty_id=asked_for, emergency=False)

    return TriageResult(specialty_id=routed, emergency=False)


async def nearest_location(ctx: ToolContext, args: NearestLocationInput) -> NearestLocationResult:
    """The closest site that can serve the request.

    Straight-line distance to the coordinates the catalogue publishes, among
    the sites that have somebody in the specialty. The closest site with nobody
    for the specialty is skipped — physiotherapy sits only at Sur, so a caller
    next door to Centro still goes to Sur. That is not a refusal.
    """
    catalogue = await ctx.clinic.catalogue()
    sites = eligibility.sites_serving(catalogue, args.specialty_id, None)
    if not sites:
        return NearestLocationResult(
            rejection=Rejection(
                reason="type_not_offered",
                detail=f"no site has anybody in {args.specialty_id}",
            )
        )

    # The geocode cache lives in this call's state, so an address never outlives
    # the socket that spoke it.
    cache = ctx.state.setdefault(geo.GEOCODE_CACHE_KEY, {})
    point = await geo.locate(args.address, _settings_of(ctx), cache)
    if point is not None:
        found = geo.nearest(point, sites)
        if found is not None:
            site, distance = found
            return NearestLocationResult(
                location_id=site.location_id, distance_km=round(distance, 2)
            )

    # Nothing placed the address. Before giving up, see whether it simply names
    # the street one of the sites is on.
    scored = [(geo.address_overlap(args.address, s.address), s) for s in sites if s.address]
    best = max(scored, default=(0, None), key=lambda pair: pair[0])
    if best[0] > 0 and best[1] is not None:
        return NearestLocationResult(location_id=best[1].location_id)

    return NearestLocationResult(
        rejection=Rejection(
            reason="out_of_scope",
            detail=f"could not place {args.address!r}; ask the caller for a district or town",
        )
    )


async def find_provider(ctx: ToolContext, args: FindProviderInput) -> ProviderMatch:
    """Match a spoken provider name against the catalogue.

    Near-miss pairs (Sáez/Sáenz, Iglesias/Iglesia) surface as ``ambiguous``
    with both candidates when ``specialty_id`` isn't given to tell them apart;
    passing it filters the pool first, so the same spoken name resolves
    cleanly once the specialty is known.

    A ``specialty_id`` that matches nobody of that name is a guess, not a
    fact: the caller named a doctor, and the specialty was most often inferred
    from a complaint the table did not recognise. Rather than report a doctor
    who exists as ``provider_not_found``, the whole catalogue answers and the
    match carries the specialty that doctor really consults in.
    """
    catalogue = await ctx.clinic.catalogue()
    matches = _providers_named(catalogue, args.spoken_name, args.specialty_id)
    if not matches and args.specialty_id:
        matches = _providers_named(catalogue, args.spoken_name, None)
        if len(matches) == 1:
            ctx.log.event(
                "find_provider.specialty_corrected",
                spoken_name=args.spoken_name,
                asked_for=args.specialty_id,
                specialty_id=matches[0].specialty_id,
            )

    if not matches:
        return ProviderMatch(status="not_found", rejection=Rejection(reason="provider_not_found"))
    if len(matches) > 1:
        return ProviderMatch(status="ambiguous", candidates=matches)

    provider = matches[0]
    today = ctx.now.astimezone(MADRID).date()
    on_leave = next((lv for lv in provider.leave if lv.date_from <= today <= lv.date_to), None)
    if on_leave:
        return ProviderMatch(
            status="on_leave",
            provider=provider,
            rejection=Rejection(reason="provider_on_leave", detail=on_leave.reason),
        )
    return ProviderMatch(status="found", provider=provider)


async def clinic_facts(ctx: ToolContext, args: ClinicFactsInput) -> ClinicFacts:
    """Which sites, who sits where, when a site opens - from the catalogue.

    Problem 16 is scored on the booking made after the answer: tell a caller
    Norte opens on Saturday and they ask for Norte on Saturday, which no tool
    can book. So the answer is the catalogue's, filtered to what they asked,
    and the site ids in it are the ids ``find_slots`` then takes.
    """
    catalogue = await ctx.clinic.catalogue()
    today = ctx.now.astimezone(MADRID).date()
    return facts.answer(catalogue, args, today)
