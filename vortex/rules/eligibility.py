"""The clinic's standing restrictions, derived from the catalogue.

``/availability`` is the authority: when it refuses a provider it names the
rule in ``blocked``, and that name is the ``reason`` we submit. But it answers
about *providers*, and only once a request is concrete enough to ask about. The
rules in this module are the ones that are plain facts on the records the
catalogue publishes — the specialty's age window, the specialty's referral
flag, the plan's covered specialties, sites and providers — so they can be read
off the patient and the catalogue without guessing anything:

- a child's age against ``SpecialtyRecord.min_age_months`` / ``max_age_months``
- ``SpecialtyRecord.referral_required`` against ``PatientRecord.referrals``
- ``InsurancePlanRecord.specialty_ids`` / ``location_ids`` / ``provider_ids``
- ``ProviderRecord.insurer_ids_refused`` and ``ProviderRecord.leave``

Each returns the one ``DeclineReason`` that names it, which is why the closed
vocabulary's first eleven values map one-for-one onto the clinic's
restrictions: there is always a value for the rule that actually bit.

The five insurance refusal shapes of problem 6 are all here, and they are not
interchangeable:

===========================  ================================
plan refuses the specialty   ``specialty_not_covered``
plan refuses the site        ``location_not_covered``
provider refuses the plan    ``provider_not_in_network``
plan demands its own         ``insurer_referral_required``
plan out of visits this year ``allowance_exhausted``
===========================  ================================

The order the checks run in is the order the clinic would hit them, widest
first: an under-14 asking for general practice is an age refusal whatever their
insurer says.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from vortex.contract import (
    Catalogue,
    DeclineReason,
    InsurancePlanRecord,
    LocationRecord,
    PatientRecord,
    ProviderRecord,
    SpecialtyRecord,
)

#: Self-pay. A plan a patient holds or does not — never a fallback we quote to
#: unlock a booking the caller's real plan refuses.
SELF_PAY = "privado"


@dataclass(frozen=True)
class RuleVerdict:
    """One rule, and what it forbids. ``reason`` is what gets submitted."""

    reason: DeclineReason
    detail: str
    #: Providers who could serve the same request instead. Empty when the rule
    #: leaves nowhere to go (Adeslas and gynaecology: one gynaecologist).
    redirect_to: list[ProviderRecord] = field(default_factory=list)


def age_in_months(born: date, on: date) -> int:
    """Complete months lived. The 14th birthday is 168 months, to the day."""
    months = (on.year - born.year) * 12 + (on.month - born.month)
    if on.day < born.day:
        months -= 1
    return months


def specialty_for_age(catalogue: Catalogue, months: int) -> SpecialtyRecord | None:
    """The age-limited specialty whose window holds this age.

    Paediatrics and general practice split at the 14th birthday with no gap and
    no overlap, so exactly one of them answers for a general complaint. This is
    what an age refusal redirects to.
    """
    for specialty in catalogue.specialties:
        if specialty.min_age_months is None and specialty.max_age_months is None:
            continue
        if _age_fits(specialty, months):
            return specialty
    return None


def _age_fits(specialty: SpecialtyRecord, months: int) -> bool:
    if specialty.min_age_months is not None and months < specialty.min_age_months:
        return False
    return not (specialty.max_age_months is not None and months > specialty.max_age_months)


def resolve_plan(
    catalogue: Catalogue, patient: PatientRecord | None, named: str | None
) -> InsurancePlanRecord | None:
    """The plan this request is quoted against.

    The caller's word wins: the second policy of problem 17 exists nowhere in
    the API, so a plan named on the call is the only way to find it. The one
    exception is self-pay, which is a plan a patient holds or does not. Quoting
    ``privado`` for someone whose record says otherwise is inventing cover to
    get past a refusal, so it falls back to the plan on the record.
    """
    wanted = (named or "").strip().lower()
    on_file = (patient.insurer if patient else "").strip().lower()
    if wanted == SELF_PAY and on_file and on_file != SELF_PAY:
        wanted = on_file
    if not wanted:
        wanted = on_file
    if not wanted:
        return None
    return next((p for p in catalogue.insurance_plans if p.insurer_id.lower() == wanted), None)


def holds_referral(patient: PatientRecord | None, specialty_id: str | None) -> bool:
    if patient is None or specialty_id is None:
        return False
    return specialty_id in {r.lower() for r in patient.referrals}


def providers_for(
    catalogue: Catalogue,
    specialty_id: str | None,
    *,
    location_id: str | None = None,
    plan: InsurancePlanRecord | None = None,
    exclude: set[str] | None = None,
) -> list[ProviderRecord]:
    """Everyone who could take this request. The redirect list, in one place."""
    out = []
    for provider in catalogue.providers:
        if specialty_id and provider.specialty_id != specialty_id:
            continue
        if location_id and location_id not in provider.location_ids:
            continue
        if exclude and provider.provider_id in exclude:
            continue
        if plan and not accepts_plan(provider, plan):
            continue
        out.append(provider)
    return out


def accepts_plan(provider: ProviderRecord, plan: InsurancePlanRecord) -> bool:
    """Whether this provider bills this plan. Refusal is per provider."""
    insurer = plan.insurer_id.lower()
    if insurer in {i.lower() for i in provider.insurer_ids_refused}:
        return False
    # A plan that lists the providers it works with excludes everyone else.
    return not (plan.provider_ids and provider.provider_id not in plan.provider_ids)


def sites_serving(
    catalogue: Catalogue, specialty_id: str | None, location_id: str | None
) -> list[LocationRecord]:
    """The sites where this request could physically happen."""
    hosts = {
        loc_id
        for provider in catalogue.providers
        if not specialty_id or provider.specialty_id == specialty_id
        for loc_id in provider.location_ids
    }
    return [
        loc
        for loc in catalogue.locations
        if loc.location_id in hosts and (not location_id or loc.location_id == location_id)
    ]


def check_patient_rules(
    catalogue: Catalogue,
    patient: PatientRecord | None,
    *,
    specialty_id: str | None,
    location_id: str | None,
    plan: InsurancePlanRecord | None,
    today: date,
    visits_this_year: int | None = None,
) -> RuleVerdict | None:
    """The rules that bite before any particular doctor is chosen.

    ``None`` means these rules allow it — not that a slot exists, which only
    ``/availability`` knows.
    """
    specialty = next((s for s in catalogue.specialties if s.specialty_id == specialty_id), None)

    # 1. Age. The widest rule: it decides which specialty the caller belongs in
    #    before anything about insurance is asked.
    if specialty and patient and patient.date_of_birth:
        months = age_in_months(patient.date_of_birth, today)
        if not _age_fits(specialty, months):
            correct = specialty_for_age(catalogue, months)
            return RuleVerdict(
                reason="not_eligible_age",
                detail=(
                    f"{specialty.name} takes "
                    f"{_window_text(specialty)}; the patient is {months} months old"
                ),
                redirect_to=(
                    providers_for(catalogue, correct.specialty_id, location_id=location_id)
                    if correct
                    else []
                ),
            )

    # 2. The specialty's own referral requirement, against the referrals the
    #    directory record carries. No record is not the same as no referral:
    #    without one this stands down and /availability answers, exactly as the
    #    age rule above does. (``/directory`` has no lookup by id, so a record
    #    is not always in hand.)
    if (
        specialty
        and specialty.referral_required
        and patient
        and not holds_referral(patient, specialty_id)
    ):
        return RuleVerdict(
            reason="referral_required",
            detail=f"{specialty.name} needs a referral and the record holds none",
        )

    if plan is None:
        return None

    # 3. The plan refuses the specialty. Adeslas and gynaecology: there is one
    #    gynaecologist, so there is nowhere to redirect to.
    if plan.specialty_ids and specialty_id and specialty_id not in plan.specialty_ids:
        return RuleVerdict(
            reason="specialty_not_covered",
            detail=f"{plan.name} does not cover {specialty_id}",
        )

    # 4. The plan refuses the site. A refusal only when *no* site that could
    #    serve the request is covered — ASISA covers physiotherapy at Centro
    #    and Norte, and the one physiotherapist sits at Sur.
    if plan.location_ids:
        candidates = sites_serving(catalogue, specialty_id, location_id)
        if candidates and not any(loc.location_id in plan.location_ids for loc in candidates):
            named = f" at {location_id}" if location_id else ""
            return RuleVerdict(
                reason="location_not_covered",
                detail=f"{plan.name} does not cover {specialty_id}{named}",
            )

    # 5. The plan demands its own referral, on top of the specialty's.
    if plan.referral_required and not holds_referral(patient, specialty_id):
        return RuleVerdict(
            reason="insurer_referral_required",
            detail=f"{plan.name} requires its own referral",
        )

    # 6. The plan has run out of visits for the year.
    if (
        plan.yearly_allowance is not None
        and visits_this_year is not None
        and visits_this_year >= plan.yearly_allowance
    ):
        return RuleVerdict(
            reason="allowance_exhausted",
            detail=(
                f"{plan.name} allows {plan.yearly_allowance} visits a year; "
                f"{visits_this_year} are used"
            ),
        )
    return None


def check_provider_rules(
    catalogue: Catalogue,
    provider: ProviderRecord | None,
    *,
    specialty_id: str | None,
    location_id: str | None,
    plan: InsurancePlanRecord | None,
    today: date,
) -> RuleVerdict | None:
    """The rules that bite once the caller has named a doctor.

    Only consulted when ``/availability`` did not already name one: the live
    API is the authority on its own providers.
    """
    if provider is None:
        return None
    specialty = specialty_id or provider.specialty_id

    if plan and not accepts_plan(provider, plan):
        return RuleVerdict(
            reason="provider_not_in_network",
            detail=f"{provider.name} does not take {plan.name}",
            redirect_to=providers_for(
                catalogue,
                specialty,
                location_id=location_id,
                plan=plan,
                exclude={provider.provider_id},
            ),
        )

    leave = next((lv for lv in provider.leave if lv.date_from <= today <= lv.date_to), None)
    if leave:
        return RuleVerdict(
            reason="provider_on_leave",
            detail=leave.reason or f"{provider.name} is on leave",
            redirect_to=providers_for(
                catalogue,
                specialty,
                location_id=location_id,
                plan=plan,
                exclude={provider.provider_id},
            ),
        )
    return None


def _window_text(specialty: SpecialtyRecord) -> str:
    low, high = specialty.min_age_months, specialty.max_age_months
    if low is not None and high is not None:
        return f"{low}-{high} months"
    if low is not None:
        return f"{low} months and over"
    if high is not None:
        return f"up to {high} months"
    return "any age"
