"""Where the points are, and where the published roster stops telling us.

    uv run python -m evals corpus --coverage

Two tables. The first ranks the eighteen problems by what one ``Run All`` can
put on the board — 196 points, unevenly spread: The Real Call is worth five
times The Simple Booking per case. The second names, per problem, what the
private pool can draw that the public roster never shows, which is the list of
things an agent can pass every published case and still fail on.

Nothing here runs the agent. It reads the roster and the published rules and
says where to spend the next hour.
"""

from __future__ import annotations

from dataclasses import dataclass

from evals.corpus import probes
from evals.corpus.catalogue import PROBLEMS, Roster, load, max_points


@dataclass(frozen=True)
class Gap:
    problem: int
    title: str
    points_at_stake: int
    public_shows: str
    private_can_draw: str


def gaps(roster: Roster | None = None) -> list[Gap]:
    """What the four cases we can see do not tell us about the four we cannot."""
    roster = roster or load()
    seen_reasons = {r for c in roster.cases for r in c.reasons}
    unreached = probes.unreached_reasons(seen_reasons)
    languages = sorted({c.language for c in roster.by_problem("languages")})
    out = [
        Gap(
            5,
            "When Exactly",
            _stake("when_exactly"),
            f"{len(roster.by_problem('when_exactly'))} of the 27 published phrases",
            "all 27, against whichever day the call lands on and the closure calendar "
            "(Sunday, Saturday outside Centro, Fiesta Nacional on Monday 12 October)",
        ),
        Gap(
            6,
            "The Rules",
            _stake("the_rules"),
            f"{len(seen_reasons & set(probes.RULE_REASONS))} of the 11 rule reasons: "
            + ", ".join(sorted(seen_reasons & set(probes.RULE_REASONS)) or ["none"]),
            "all five refusal shapes; never shown here: " + ", ".join(unreached),
        ),
        Gap(
            10,
            "Triage",
            _stake("triage"),
            f"{len(roster.by_problem('triage'))} of the 20 published complaints",
            "all 15 symptom rows and all 5 red flags",
        ),
        Gap(
            11,
            "Languages",
            _stake("languages"),
            f"{len(roster.by_problem('languages'))} cases in {', '.join(languages)}",
            "Catalan far more often — the docs say so outright — and the other "
            "languages of Spain. Only four providers speak Catalan",
        ),
        Gap(
            4,
            "The New Patient",
            _stake("the_new_patient"),
            f"{len(roster.by_problem('the_new_patient'))} dictated identities",
            "any DNI or NIE: the check letter is arithmetic, so a misheard digit and "
            "an invented id are distinguishable, and the email has no check at all",
        ),
        Gap(
            3,
            "The Doctor and the Site",
            _stake("doctor_and_site"),
            f"{len(roster.by_problem('doctor_and_site'))} named providers",
            "both near-miss pairs (Sáez/Sáenz, Iglesias/Iglesia), the physiotherapist "
            "whose title is D. and not Dr., and Requena's leave across the whole event",
        ),
        Gap(
            14,
            "Adversarial and Privacy",
            _stake("adversarial"),
            f"{sum(1 for c in roster.by_problem('adversarial') if c.protected)} of "
            f"{len(roster.by_problem('adversarial'))} cases carry protected fields",
            "any injection, any request for another patient's data. The transcript is "
            "read as well as the record, and reading an id out digit by digit is the leak",
        ),
        Gap(
            18,
            "The Real Call",
            _stake("the_real_call"),
            f"{len(roster.by_problem('the_real_call'))} stacked calls — the smallest "
            "public pool and the largest weight",
            "two intents, a mind changed halfway, noise, and a third party at once. "
            "Every lane has to be right in the same call",
        ),
    ]
    return sorted(out, key=lambda g: -g.points_at_stake)


def _stake(problem_id: str) -> int:
    _, _, weight, pool = PROBLEMS[problem_id]
    return weight * pool


def print_report(roster: Roster | None = None) -> None:
    roster = roster or load()
    print(f"\nThe roster: {len(roster.cases)} published cases, sha256 {roster.sha256[:12]}")
    print(f"One Run All is worth {max_points()} points. They are not spread evenly.\n")

    print(f"{'#':>3}  {'problem':24} {'w':>2} {'stake':>6} {'public':>7}  shapes")
    print("-" * 96)
    rows = sorted(PROBLEMS.items(), key=lambda kv: (-kv[1][2] * kv[1][3], kv[1][0]))
    for problem_id, (number, title, weight, pool) in rows:
        cases = roster.by_problem(problem_id)
        shapes = ", ".join(sorted({c.shape() for c in cases})) or "—"
        stake = weight * pool
        print(f"{number:>3}  {title[:24]:24} {weight:>2} {stake:>6} {len(cases):>7}  {shapes[:44]}")
    print("-" * 96)
    print(f"{'':>3}  {'total':24} {'':>2} {max_points():>6} {len(roster.cases):>7}\n")

    print("Where the published cases stop telling us anything\n")
    for gap in gaps(roster):
        print(f"  {gap.problem:>2}. {gap.title}  ·  {gap.points_at_stake} points at stake")
        print(f"      public shows:  {gap.public_shows}")
        print(f"      private draws: {gap.private_can_draw}")
        print()

    print("Facts the docs state and no published case exercises\n")
    for fact, consequence in probes.KNOWN_INTERACTIONS:
        print(f"  · {fact}")
        print(f"    -> {consequence}")
    print()
