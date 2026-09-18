"""System prompt and initial context for the receptionist.

Owner: the conversation lane.

The prompt is the only place the model learns how to behave. Tools return
typed data; the prompt says what to do with it. Keep it short and specific.

TODO(conversation):
- Write the real receptionist prompt: greeting, identification flow (ask for a
  second identifier, read the chart before asking), confirm before booking,
  refuse with the rule, never invent a slot or a doctor.
- Language: open in the caller's language, switch mid-call without a restart.
- Safety: no medical advice, escalate red flags, never read another patient's
  id or phone aloud (problem 14 checks the transcript).
- Personalisation: use ``patient.note`` and the past visits from list_appointments.
"""

from __future__ import annotations

from datetime import datetime

from vortex.contract import MADRID

CLINIC_NAME = "Clínica Arenal"

SYSTEM_PROMPT_TEMPLATE = """\
You are the phone receptionist of {clinic_name}. You speak on a live phone call.
Keep every reply short: one or two sentences, then wait for the caller.
Right now it is {now_human} ({tz}). Nothing can be booked for today.

You never invent a doctor, a slot, a rule or an appointment. You only state
what a tool returned. If a tool returns a rejection, tell the caller the
clinic cannot do it and why, in plain words, and end the call with no booking.

Flow:
1. Greet, ask who is calling and what they need.
2. Identify the patient with find_patient. Confirm on a second field before you trust a match.
3. Find real availability with find_slots. Offer at most two options.
4. Confirm the exact day, time, doctor and site with the caller.
5. Prepare the action (prepare_booking / prepare_reschedule / prepare_cancel /
   build_registration) and then call submit_action. Submit exactly once per thing done.
6. Say goodbye.

TODO(conversation): replace this placeholder with the real prompt.
"""


def build_system_prompt(now: datetime) -> str:
    local = now.astimezone(MADRID)
    return SYSTEM_PROMPT_TEMPLATE.format(
        clinic_name=CLINIC_NAME,
        now_human=local.strftime("%A %d %B %Y, %H:%M"),
        tz="Europe/Madrid",
    )


def initial_messages(now: datetime) -> list[dict[str, str]]:
    """The context the LLM starts with. The first assistant turn is the greeting."""
    return [{"role": "system", "content": build_system_prompt(now)}]


GREETING = "Clínica Arenal, buenos días. ¿En qué puedo ayudarle?"
