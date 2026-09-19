"""System prompt, greeting and canned lines for the receptionist.

Owner: the conversation lane.

The prompt text is a versioned file: ``prompts/<version>.md``, ``<version>``
= ``v<N>-<slug>`` (``v3-specialty-ids``). ``build_system_prompt`` loads the
one named by ``VORTEX_PROMPT_VERSION``, or the latest on disk when the
variable is unset. A version file is never edited in place: a change is a
new version and the old one stays for the diff. Every evals run records the
version in force and its sha256 beside the model (``evals/common/results.py``),
so two runs are comparable and a baseline is a ``(prompt_version, model)``
pair, not a layer alone. The version file holds the fixed text with
``{placeholder}`` holes; the clock, the language, the caller block and the
tool guide are rendered in per call, so the model never does calendar
arithmetic itself.

The prompt is the only place the model learns how to behave. Tools return
typed data; the prompt says what to do with it. It is written for a small,
fast model on a phone line (short replies, one question per turn, no lists)
and it is built per call from the version file.

It is sent on every turn, so it has a budget: ``tests/test_prompt.py`` fails
the build over ~1,400 tokens. That is what keeps this file procedural rather
than literary - every sentence has to earn its place against a rule the
scorer or the jury can see. ``TOOL_GUIDE`` is part of that budget and says
only what a tool's own JSON schema cannot: which field of the answer the next
step depends on.

The one thing outside that budget is the CALLER block (``caller_note_for``),
built per call from the caller-id lookup. It costs 130-160 tokens a turn and
is the only part of the prompt that is not the same for everyone, because it
replaces something far more expensive: the two-to-six turns the call used to
spend establishing who is on the line. ``tests/test_caller_id_prefetch.py``
owns its ceiling.

What it must achieve, and why each rule is there:

- A submission on every call, inside three minutes. A call with no accepted
  record is a failed case, so every path ends in ``submit_action``.
- Ids only from tools. A guessed ``patient_id`` or ``slot`` fails the case
  even when the conversation was perfect.
- English by default. 69 of the 73 public cases are English; the caller who
  speaks Spanish or Catalan is the exception, and we follow them.
- Nothing from a chart is read aloud. Problem 14 scans our turns for a
  patient's national id and phone after normalisation, digit by digit
  included. The name is not protected; everything else stays off the line.
  So confirmation is done by asking, never by telling: on a mismatch we ask
  the caller to say the whole id or phone again in groups of three, rather than
  reading back what we heard or proposing a single character of it.
- The final stated request wins. Problem 13 books what the caller said last.
- Read-back protocol (noise and alphanumerics): one field per turn, digits in
  groups of three, names and email read back once, last value wins on a
  correction. National id and phone stay silent (problem 14).
- Read the chart before asking. ``has_visited_before`` and ``note`` say who
  this is; the jury judges on it.
- An empty window is an offer, not a refusal (problem 7). ``find_slots``
  fills ``nearest`` with the closest slots that keep the request; the model
  offers them and books only what the caller takes. Refused, or nothing near:
  the rejection's reason, ``no_availability``, and nothing else.
- ``check_eligibility`` before offering, not after. ``find_slots`` answers
  from the diary and happily returns slots a plan does not cover, so the
  refusal problems (6, 17) are decided by the eligibility verdict; the
  ``reason`` it carries is the ``reason`` we submit.
- One confirmation. The caller's first yes to a read-back is the agreement;
  reading the plan back a second time costs the wall clock and, on the scored
  run, the submission itself. ``conversation.turns.ConfirmationPolicy`` is the
  same rule off the model's path.
- A registration rejection names the field to fix, not a reason to hang up.
  ``build_registration``'s rejection is the one rejection the call must
  survive: repeat that field and try again, instead of closing with no action.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from vortex.contract import MADRID, CallerLineMatch
from vortex.conversation.language import DEFAULT_LANGUAGE, language_name, normalise_language

CLINIC_NAME = "Clínica Arenal"

# The versioned prompt files. ``v<N>-<slug>.md``, never edited in place: a
# change is a new version and the old one stays for the diff. The version in
# force is ``VORTEX_PROMPT_VERSION``, or the highest ``v<N>`` on disk.
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
VERSION_RE = re.compile(r"^v(\d+)-[a-z0-9-]+$")

# The three site ids, so a caller who names a site can be quoted the right
# location_id without a round trip. Nothing else about a site lives here: no
# hours, no closures, no towns, no doctors. Problem 16 is scored on the
# booking made after we answer such a question, so a fact stated from memory
# ("Norte opens Saturday") becomes an unbookable request. clinic_facts reads
# the catalogue; the prompt tells the model to ask it, every time.
SITES_BRIEF = "Sites: Centro = centro, Norte = norte, Sur = sur."

# The six specialty ids, so the model never invents one. "general_medicine"
# cost problem 1 on the 2026-09-18 replay: find_slots answers nothing for an
# id the catalogue does not hold, and the call died as no_availability with
# bookable slots on the wall. Where the id comes from is still rule 8 - triage,
# or the named doctor's specialty; this line only closes the vocabulary, the
# same job SITES_BRIEF does for locations. Six is all of them: the catalogue
# holds no other.
SPECIALTIES_BRIEF = (
    "Specialty ids: general_practice, paediatrics, dermatology, "
    "orthopaedics, gynaecology, physiotherapy."
)

# One line per tool: when to call it, and what to trust in the answer. The
# tool's own ``description`` (vortex/tools.py) already says what it does and
# is sent with the schema, so these lines carry only what a schema cannot:
# the order to call them in, and which field of the answer is load-bearing.
#
# Keyed by tool name so the guide cannot drift from the list the model is
# actually given: ``TOOL_GUIDE`` renders in ``DEFAULT_EXPOSED_TOOLS`` order,
# and a tool added to that list with no line here fails tests/test_prompt.py.
TOOL_LINES: dict[str, str] = {
    "find_patient": "status, patient_id, ask_for.",
    "validate_national_id": "valid. Re-ask it whole, never read it back.",
    "build_registration": "action. Never read a rejected field back.",
    "resolve_date": 'the window. "the earliest" works.',
    "find_slots": "slots, nearest, blocked.",
    "list_appointments": "the only appointment_id.",
    "prepare_booking": "action or rejection.",
    "prepare_reschedule": "action.",
    "prepare_cancel": "action.",
    "check_eligibility": "allowed, reason, redirect_to.",
    "triage": "specialty_id, emergency. A symptom only, never a specialty; provider_name if named.",
    "nearest_location": "location_id.",
    "find_provider": "status, provider_id.",
    "clinic_facts": "sites, open_days, providers.",
    "submit_action": "status. Nothing counts without it.",
}


def _version_key(stem: str) -> tuple[int, str]:
    match = re.match(r"v(\d+)-", stem)
    return (int(match.group(1)) if match else -1, stem)


def list_prompt_versions(directory: Path | None = None) -> list[str]:
    """Every version on disk, oldest first. Names must be ``v<N>-<slug>``."""
    directory = directory or PROMPTS_DIR
    return sorted(
        (p.stem for p in directory.glob("*.md") if VERSION_RE.match(p.stem)),
        key=_version_key,
    )


def latest_prompt_version(directory: Path | None = None) -> str:
    """The highest ``v<N>`` on disk - what a run uses when the env says nothing."""
    versions = list_prompt_versions(directory)
    if not versions:
        raise FileNotFoundError(f"no prompt version file in {directory} (v<N>-<slug>.md)")
    return versions[-1]


def active_prompt_version(directory: Path | None = None) -> str:
    """The version in force: ``VORTEX_PROMPT_VERSION``, else the latest on disk."""
    return os.environ.get("VORTEX_PROMPT_VERSION", "").strip() or latest_prompt_version(directory)


def _version_path(version: str, directory: Path | None) -> Path:
    directory = directory or PROMPTS_DIR
    if not VERSION_RE.match(version):
        raise ValueError(
            f"prompt version {version!r} is not a v<N>-<slug> name; "
            f"on disk: {', '.join(list_prompt_versions(directory)) or 'none'}"
        )
    return directory / f"{version}.md"


def load_prompt_template(version: str | None = None, directory: Path | None = None) -> str:
    """The raw text of one prompt version, placeholders and all.

    ``None`` means the version in force (``active_prompt_version``). Read per
    call, never cached: the file named by the env var may change between
    processes, and a version file is never edited in place, so there is
    nothing to invalidate.
    """
    resolved = version or active_prompt_version(directory)
    path = _version_path(resolved, directory)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        available = ", ".join(list_prompt_versions(directory)) or "none"
        raise ValueError(
            f"unknown prompt version {resolved!r}: no {path.name} in {path.parent.name}/. "
            f"Versions on disk: {available}"
        ) from None


def prompt_sha256(version: str | None = None, directory: Path | None = None) -> str:
    """The sha256 of a version file, hex - what every evals run records."""
    resolved = version or active_prompt_version(directory)
    return hashlib.sha256(_version_path(resolved, directory).read_bytes()).hexdigest()


def tool_guide(names: list[str] | None = None) -> str:
    """The one-line-per-tool guide, in the order the model is given them."""
    from vortex.conversation.turns import DEFAULT_EXPOSED_TOOLS

    exposed = DEFAULT_EXPOSED_TOOLS if names is None else names
    lines = [f"{name}: {TOOL_LINES[name]}" for name in exposed if name in TOOL_LINES]
    return "TOOLS - what to trust.\n" + "\n".join(lines)


TOOL_GUIDE = tool_guide()


def caller_note_for(match: CallerLineMatch | None) -> str:
    """The CALLER block: who the dialling line belongs to, before a word is said.

    Empty when the line was never looked up, so a call with no caller id reads
    exactly the prompt it read before. The record's national id and birth date
    are deliberately left out: nothing in the flow needs them off this note, and
    the fewer protected fields in front of the model the less there is to say
    aloud by accident.
    """
    if match is None or not match.looked_up:
        return ""
    patient = match.patient
    if patient is None and match.candidates:
        # A shared line: several records, so it names nobody and claims nothing.
        # Saying "not registered" here would be a lie about a patient we hold.
        return ""
    if patient is None:
        return (
            "CALLER. This line is on no patient record, so they are a new patient unless "
            f"they give a name find_patient matches. Their phone is {match.from_number} - "
            "it is known, so never ask for it and never say it aloud. If they want an "
            "appointment, register them first (7).\n\n"
        )
    chart = [f"visited_before={str(patient.has_visited_before).lower()}"]
    if patient.insurer:
        chart.append(f"insurer={patient.insurer}")
    if patient.referrals:
        chart.append(f"referrals={', '.join(patient.referrals)}")
    if patient.note:
        chart.append(f"note={patient.note}")
    return (
        f"CALLER. This line belongs to {patient.full_name}, patient_id "
        f"{patient.patient_id} ({'; '.join(chart)}). That is who is calling unless they "
        "say otherwise: ask no identity questions, greet them by name and ask what they "
        "need. Calling for someone else: find_patient that person by name and birth "
        "date, and book their id.\n\n"
    )


def handoff_note_for(handoff: dict[str, str] | None) -> str:
    """The HANDOFF block: a colleague has just transferred this call to you.

    The confirmation agent called the patient about tomorrow's appointment,
    they asked to move it, and the call was handed over mid-conversation -
    "te paso con mi compañero, que te agenda las citas". You are that
    colleague: the scheduling agent. The conversation opens mid-task, with
    the rebooking flow and the diary tools, in the patient's language.
    """
    if not handoff:
        return ""
    language = language_name(handoff.get("language") or DEFAULT_LANGUAGE)
    lines = [
        "HANDOFF: A colleague has just transferred this call to you. You called the patient",
        "to confirm tomorrow's appointment and they said they want to move it "
        f"(appointment_id: {handoff.get('appointment_id', 'unknown')}, "
        f"patient_id: {handoff.get('patient_id', 'unknown')}).",
        "The patient is ALREADY IDENTIFIED - we placed this call to their registered number,",
        "so the Identify step is done. Never ask for their name, national id, birth date or",
        "any personal data again on this call; if a tool needs the patient, use the patient_id",
        "above. The patient knows you are the colleague who books the appointments. Do not ask",
        "who is calling or what they need: go straight to rescheduling that appointment with",
        "the diary tools and submit the change.",
        f"The patient speaks {language}; continue in {language}.",
    ]
    return "\n".join(lines)


HANDOFF_GREETINGS: dict[str, str] = {
    "es": "Hola, soy el compañero que le agenda las citas. Vamos a mover la suya: "
    "¿qué día le viene mejor?",
    "ca": "Hola, sóc el company que li agenda les cites. Anem a moure la seva: "
    "quin dia li va millor?",
    "gl": "Ola, son o compañeiro que lle axenda as citas. Imos mover a súa: "
    "que día lle ven mellor?",
    "eu": "Kaixo, hitzorduak kudeatzen dituen kidea naiz. Zurea mugituko dugu: "
    "zein egun datorkizun ondo?",
    "en": "Hello, I'm the colleague who books your appointments. Let's move yours: "
    "which day suits you best?",
}


def handoff_greeting_for(language: str | None = None) -> str:
    """The line a handoff call opens with: mid-task, straight to rescheduling."""
    return _line(HANDOFF_GREETINGS, language)


def build_system_prompt(
    now: datetime,
    *,
    language: str | None = None,
    caller: CallerLineMatch | None = None,
    handoff: dict[str, str] | None = None,
    version: str | None = None,
) -> str:
    """The system prompt for one call, with the clock rendered in.

    ``language`` is the language the caller opened in when it is already
    known (a repeat caller, a language header); the default is English.
    ``caller`` is the caller-id lookup, when the line lane got one back in
    time; it saves the call the whole identify exchange. The fixed text is
    the prompt version in force (``VORTEX_PROMPT_VERSION``, else the latest
    on disk); ``version`` pins one explicitly.
    """
    local = now.astimezone(MADRID)
    return load_prompt_template(version).format(
        clinic_name=CLINIC_NAME,
        now_human=local.strftime("%H:%M on %A %d %B %Y"),
        tomorrow=(local + timedelta(days=1)).strftime("%A %d %B %Y"),
        language=language_name(language or DEFAULT_LANGUAGE),
        sites_brief=SITES_BRIEF,
        specialties_brief=SPECIALTIES_BRIEF,
        caller_note="\n".join(
            part for part in (caller_note_for(caller), handoff_note_for(handoff)) if part
        ),
        tool_guide=TOOL_GUIDE,
    )


def initial_messages(
    now: datetime,
    *,
    language: str | None = None,
    caller: CallerLineMatch | None = None,
    handoff: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """The context the LLM starts with. The first assistant turn is the greeting."""
    return [
        {
            "role": "system",
            "content": build_system_prompt(now, language=language, caller=caller, handoff=handoff),
        }
    ]


# ---------------------------------------------------------------------------
# Canned lines. Spoken outside the model (the greeting before the first
# frame, the idle nudge, the emergency line), so they must exist in every
# language we can detect. The model says everything else.
# ---------------------------------------------------------------------------

GREETINGS: dict[str, str] = {
    "en": "Clínica Arenal, hello. How can I help you?",
    "es": "Clínica Arenal, buenos días. ¿En qué puedo ayudarle?",
    "ca": "Clínica Arenal, bon dia. En què puc ajudar-lo?",
    "gl": "Clínica Arenal, bos días. En que podo axudalo?",
    "eu": "Clínica Arenal, egun on. Zertan lagun zaitzaket?",
}

# The first nudge, at ``TurnSettings.user_idle_secs`` of silence.
IDLE_PROMPTS: dict[str, str] = {
    "en": "Are you still there?",
    "es": "¿Sigue ahí?",
    "ca": "Encara hi és?",
    "gl": "Segue aí?",
    "eu": "Hor zaude oraindik?",
}

# The second nudge, and the last one for a while. Asking "are you still there?"
# twice makes the caller restart the sentence they were already saying, which
# is what cost the 2026-09-18 run ~10 s a nudge; this line gives them the
# silence instead. See ``conversation.turns.IdlePolicy``.
IDLE_PATIENCE_PROMPTS: dict[str, str] = {
    "en": "No rush. Take your time.",
    "es": "Sin prisa. Tómese el tiempo que necesite.",
    "ca": "Sense pressa. Prengui's el temps que necessiti.",
    "gl": "Sen presa. Tome o tempo que precise.",
    "eu": "Lasai. Hartu behar duzun denbora.",
}

# Said when *we* are the ones who went quiet: the model's completion produced
# no first token and the line gave up on it (vortex/line/llm_timeout.py). It
# has to be a finished sentence — the TTS flushes on sentence boundaries, and
# a fragment would sit in the aggregator unsaid.
WAIT_LINES: dict[str, str] = {
    "en": "One moment, please.",
    "es": "Un momento, por favor.",
    "ca": "Un moment, si us plau.",
    "gl": "Un momento, por favor.",
    "eu": "Momentu bat, mesedez.",
}

# Spoken on the second idle, just before we submit what the call already knows.
IDLE_SUBMIT_LINES: dict[str, str] = {
    "en": "I'll note what we have so far. Thank you for calling.",
    "es": "Anoto lo que tenemos por ahora. Gracias por llamar.",
    "ca": "Anoto el que tenim de moment. Gràcies per trucar.",
    "gl": "Anoto o que temos por agora. Grazas por chamar.",
    "eu": "Orain artekoa idatziko dut. Eskerrik asko deitzeagatik.",
}

# Said the moment triage flags a red flag. "112" is the check the harness runs.
EMERGENCY_LINES: dict[str, str] = {
    "en": "This sounds like an emergency. Please hang up and call 112 right now.",
    "es": "Esto parece una emergencia. Cuelgue y llame al 112 ahora mismo, por favor.",
    "ca": "Això sembla una emergència. Pengi i truqui al 112 ara mateix, si us plau.",
    "gl": "Isto parece unha emerxencia. Colgue e chame ao 112 agora mesmo, por favor.",
    "eu": "Larrialdi bat dirudi. Eseki eta deitu 112ra oraintxe bertan, mesedez.",
}

REFUSAL_LINES: dict[str, str] = {
    "en": "I'm sorry, I can't help with that. I can book, move or cancel an appointment.",
    "es": "Lo siento, no puedo ayudarle con eso. Puedo dar, cambiar o anular una cita.",
    "ca": "Ho sento, no puc ajudar-lo amb això. Puc donar, canviar o anul·lar una hora.",
    "gl": "Síntoo, non podo axudalo con iso. Podo dar, cambiar ou anular unha cita.",
    "eu": (
        "Sentitzen dut, ezin dizut horretan lagundu. "
        "Hitzordu bat eman, aldatu edo bertan behera utz dezaket."
    ),
}

GOODBYE_LINES: dict[str, str] = {
    "en": "Thank you for calling. Goodbye.",
    "es": "Gracias por llamar. Hasta luego.",
    "ca": "Gràcies per trucar. Fins aviat.",
    "gl": "Grazas por chamar. Ata logo.",
    "eu": "Eskerrik asko deitzeagatik. Agur.",
}


def _line(table: dict[str, str], language: str | None) -> str:
    return table.get(normalise_language(language) or DEFAULT_LANGUAGE, table[DEFAULT_LANGUAGE])


def greeting_for(language: str | None = None) -> str:
    return _line(GREETINGS, language)


def idle_prompt_for(language: str | None = None) -> str:
    """The first "are you still there?", in the language the call is in."""
    return _line(IDLE_PROMPTS, language)


def idle_submit_line_for(language: str | None = None) -> str:
    return _line(IDLE_SUBMIT_LINES, language)


def idle_patience_for(language: str | None = None) -> str:
    """The second nudge: tell the caller to take their time, then go quiet."""
    return _line(IDLE_PATIENCE_PROMPTS, language)


def wait_prompt_for(language: str | None = None) -> str:
    return _line(WAIT_LINES, language)


def emergency_line_for(language: str | None = None) -> str:
    return _line(EMERGENCY_LINES, language)


def refusal_line_for(language: str | None = None) -> str:
    return _line(REFUSAL_LINES, language)


def goodbye_for(language: str | None = None) -> str:
    return _line(GOODBYE_LINES, language)


# The opening line, spoken before the caller says a word. English: the
# clinic's default; the model switches as soon as the caller does.
GREETING = GREETINGS[DEFAULT_LANGUAGE]
