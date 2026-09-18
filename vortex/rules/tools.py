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

from vortex import contract
from vortex.contract import (
    CheckEligibilityInput,
    EligibilityVerdict,
    FindProviderInput,
    NearestLocationInput,
    NearestLocationResult,
    ProviderMatch,
    ToolContext,
    TriageInput,
    TriageResult,
)


async def check_eligibility(ctx: ToolContext, args: CheckEligibilityInput) -> EligibilityVerdict:
    """Can this patient book this specialty/provider/site under this plan?

    TODO(rules): read the catalogue (``await ctx.clinic.catalogue()``) and the
    patient record; return ``allowed=False`` with the matching rule reason, and
    fill ``redirect_to`` when another provider can serve the same request.
    """
    return await contract.stub_check_eligibility(ctx, args)


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

    TODO(rules): handle the near-miss pairs (Sáez/Sáenz, Iglesias/Iglesia) as
    ``ambiguous`` with both candidates, report ``on_leave`` with a
    ``provider_on_leave`` rejection, and ``not_found`` with ``provider_not_found``.
    """
    return await contract.stub_find_provider(ctx, args)
