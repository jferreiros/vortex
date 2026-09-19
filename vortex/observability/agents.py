"""The clinic's agents, as the console lists them.

One agent is real: Scheduling answers the line today. The others are the
product's roadmap and carry ``preview=True``. The console labels every
Preview surface; nothing sample ever looks live.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Agent:
    slug: str
    name: str
    role: str
    summary: str
    preview: bool
    tools: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    languages: tuple[str, ...] = ("es",)
    channels: tuple[str, ...] = ("inbound phone",)
    will_do: tuple[str, ...] = field(default_factory=tuple)

    @property
    def status_label(self) -> str:
        return "Preview" if self.preview else "On duty"


AGENTS: tuple[Agent, ...] = (
    Agent(
        slug="scheduling",
        name="Scheduling",
        role="Inbound appointments",
        summary=(
            "Answers the clinic's line, identifies the patient in the directory, applies the "
            "clinic's rules and books, moves or cancels an appointment. Refuses with a typed "
            "reason and escalates emergencies."
        ),
        preview=False,
        tools=(
            "find_patient",
            "validate_national_id",
            "build_registration",
            "resolve_date",
            "find_provider",
            "check_eligibility",
            "find_slots",
            "list_appointments",
            "prepare_booking",
            "prepare_reschedule",
            "prepare_cancel",
            "triage",
            "nearest_location",
            "submit_action",
        ),
        rules=(
            "Ids come from the clinic API, never from what the patient says",
            "Nothing same-day; the earliest slot is tomorrow",
            "Age, referral and insurance checks before any slot is offered",
            "Red-flag symptoms escalate, never book",
            "Every call ends in one submission, refusals included",
        ),
        languages=("es", "ca", "gl", "eu", "en"),
        channels=("inbound phone",),
    ),
    Agent(
        slug="reminders",
        name="Reminders",
        role="Outbound confirmations",
        summary=(
            "Calls patients the day before, confirms or frees the slot, and offers the next "
            "one when they cannot come."
        ),
        preview=True,
        tools=("list_appointments", "find_slots", "prepare_reschedule", "prepare_cancel"),
        rules=("Never calls outside site hours", "Three attempts, then a note for the desk"),
        languages=("es", "en"),
        channels=("outbound phone", "SMS"),
        will_do=(
            "Confirm tomorrow's appointments",
            "Free a slot the moment a patient cancels",
            "Offer the next free slot in the same call",
        ),
    ),
    Agent(
        slug="billing",
        name="Billing",
        role="Patient balance questions",
        summary=(
            "Answers what a visit costs, what the plan covers and what is outstanding. "
            "Takes nothing on the phone; hands payment links to the desk."
        ),
        preview=True,
        tools=("find_patient", "check_eligibility"),
        rules=("Reads balances, never edits them", "No card numbers on the call"),
        languages=("es", "en"),
        channels=("inbound phone",),
        will_do=(
            "Explain a bill line by line",
            "Say what the plan covers before the visit",
            "Route a dispute to a person",
        ),
    ),
    Agent(
        slug="insurance",
        name="Insurance verification",
        role="Coverage before the visit",
        summary=(
            "Checks the patient's plan against the clinic's matrix before the appointment "
            "and flags the visits that will be refused at the desk."
        ),
        preview=True,
        tools=("find_patient", "check_eligibility", "list_appointments"),
        rules=("Only the plans the platform knows", "A refusal names the rule"),
        languages=("es",),
        channels=("batch", "outbound phone"),
        will_do=(
            "Verify tomorrow's agenda against the insurance matrix",
            "Warn the desk about visits a plan will not cover",
            "Call the patient when a referral is missing",
        ),
    ),
    Agent(
        slug="switchboard",
        name="Switchboard",
        role="Routing and after-hours",
        summary=(
            "Picks up every call, routes it to the right agent or person, and takes a "
            "message when the clinic is closed."
        ),
        preview=True,
        tools=("nearest_location", "triage"),
        rules=("Emergencies go to 112 guidance first", "A message always reaches the desk"),
        languages=("es", "ca", "en"),
        channels=("inbound phone",),
        will_do=(
            "Answer at once, twenty lines at a time",
            "Route to Scheduling, Billing or a person",
            "Cover the night and the weekend",
        ),
    ),
)


def get_agent(slug: str) -> Agent | None:
    return next((a for a in AGENTS if a.slug == slug), None)


def real_agents() -> list[Agent]:
    return [a for a in AGENTS if not a.preview]


def preview_agents() -> list[Agent]:
    return [a for a in AGENTS if a.preview]
