"""rules/ tools - what the clinic does not do.

Owner: the rules lane. Replace each ``stub_*`` call with the real logic.
Keep the signatures exactly as ``vortex/contract.py`` declares them.

What the docs say this lane must get right (clinic docs + problems 6, 10, 15):

- Refuse with the rule that bit. The first eleven ``DeclineReason`` values
  mirror the clinic's restrictions one-for-one; /availability's ``blocked``
  names the rule for a provider.
- Age boundary: the 14th birthday, in months, no gap, no overlap.
- Referrals: some specialties need one; the patient's held referrals are on
  the directory record.
- Insurance: a plan can refuse a specialty, a site or be refused by a
  provider. ``privado`` is a plan a patient holds or not, never a fallback.
- A refused provider with an alternative is a redirect, not a refusal
  (Dra. Iglesias does not take DKV; Dr. Vilar does).
- Dr. Requena is on leave for the whole event.
- Triage: the routing table and the red flags are a published list. A red
  flag is ESCALATE(medical_emergency), never a booking.
- Nearest site: smallest straight-line distance among the sites that can
  actually serve the request.
- Closed vocabulary: ``contract.ALL_REASONS`` is the only list of reasons.
"""

from __future__ import annotations

import unicodedata
from datetime import timedelta
from difflib import SequenceMatcher

from vortex import contract
from vortex.contract import (
    MADRID,
    CheckEligibilityInput,
    EligibilityVerdict,
    FindProviderInput,
    NearestLocationInput,
    NearestLocationResult,
    ProviderMatch,
    Rejection,
    ToolContext,
    TriageInput,
    TriageResult,
)

_TITLES = {"dr", "dra", "d", "doctor", "doctora"}
_TYPO_MATCH_CUTOFF = 0.8


def _name_tokens(name: str) -> set[str]:
    """Lower-cased, accent-folded, title-stripped tokens — for surname matching."""
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    tokens = {t.strip(".,").lower() for t in folded.split()}
    return tokens - _TITLES


async def check_eligibility(ctx: ToolContext, args: CheckEligibilityInput) -> EligibilityVerdict:
    """Can this patient book this specialty/provider/site under this plan?

    Reads the answer straight from ``/availability``'s ``blocked`` for the
    exact request asked about, rather than re-deriving the insurance/age
    matrix independently (the docs are explicit: "take the exact reason from
    ``blocked``. Never guess.").
    """
    today = ctx.now.astimezone(MADRID).date()
    result = await ctx.clinic.availability(
        date_from=today + timedelta(days=1),
        date_to=today + timedelta(days=14),
        provider_id=args.provider_id,
        specialty_id=args.specialty_id,
        location_id=args.location_id,
        patient_id=args.patient_id,
        insurer=[args.insurer] if args.insurer else None,
    )
    if result.slots:
        return EligibilityVerdict(allowed=True)

    if not result.blocked:
        return EligibilityVerdict(allowed=False, rejection=Rejection(reason="no_availability"))

    blocked_ids = {b.provider_id for b in result.blocked}
    match = next(
        (b for b in result.blocked if b.provider_id == args.provider_id), result.blocked[0]
    )

    catalogue = await ctx.clinic.catalogue()
    redirect_to = [
        p
        for p in catalogue.providers
        if p.specialty_id == args.specialty_id
        and p.provider_id not in blocked_ids
        and (not args.location_id or args.location_id in p.location_ids)
    ]
    return EligibilityVerdict(
        allowed=False, rejection=Rejection(reason=match.reason), redirect_to=redirect_to
    )


async def triage(ctx: ToolContext, args: TriageInput) -> TriageResult:
    """Symptom -> specialty, or emergency.

    TODO(rules): implement the published routing table and the five red flags
    from problem 10. Keep it a lookup, not a clinical judgement.
    """
    return await contract.stub_triage(ctx, args)


async def nearest_location(ctx: ToolContext, args: NearestLocationInput) -> NearestLocationResult:
    """The closest site that can serve the request.

    TODO(rules): geocode the address (any provider; the €100 card covers it),
    compute straight-line distance to each site's published coordinates, and
    skip sites with no provider in the specialty.
    """
    return await contract.stub_nearest_location(ctx, args)


async def find_provider(ctx: ToolContext, args: FindProviderInput) -> ProviderMatch:
    """Match a spoken provider name against the catalogue.

    Near-miss pairs (Sáez/Sáenz, Iglesias/Iglesia) surface as ``ambiguous``
    with both candidates when ``specialty_id`` isn't given to tell them apart;
    passing it filters the pool first, so the same spoken name resolves
    cleanly once the specialty is known.
    """
    catalogue = await ctx.clinic.catalogue()
    pool = catalogue.providers
    if args.specialty_id:
        pool = [p for p in pool if p.specialty_id == args.specialty_id]

    # Every token the caller said (surname alone is enough) must be one of the
    # provider's tokens — deterministic, and never confuses Sáez with Sáenz,
    # since "saez" and "saenz" are different tokens even after accent-folding.
    target = _name_tokens(args.spoken_name)
    matches = [p for p in pool if target <= _name_tokens(p.name)]
    if not matches:
        # Typo-tolerant fallback: each target token fuzzy-matches some provider token.
        def _fuzzy_subset(wanted: set[str], have: set[str]) -> bool:
            return all(
                any(SequenceMatcher(None, w, h).ratio() >= _TYPO_MATCH_CUTOFF for h in have)
                for w in wanted
            )

        matches = [p for p in pool if _fuzzy_subset(target, _name_tokens(p.name))]

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
