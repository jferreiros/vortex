"""The published triage table, as a lookup.

Problem 10 publishes fifteen symptom rows and five red flags. It is a table,
not clinical judgement: the private pool draws from the same template, so the
job is to recognise a paraphrase of a published row, never to reason about
medicine.

How a complaint is read, in order:

1. **Red flags first.** Each of the five is a conjunction of signals, so a row
   that merely shares a word with one ("bleeding between periods") does not
   escalate. A red flag books nothing.
2. **A child marker wins.** Every child row in the table routes to paediatrics,
   and the age rule says an under-14 belongs there anyway.
3. **Otherwise, the best-scoring specialty**, from the patterns each published
   row contributes.
4. **General practice is the residue.** Four of the fifteen rows are
   unremarkable adult complaints; nothing published routes to "unknown".

Callers phone in English, Spanish and Catalan (69/3/1 of the public roster), so
every pattern carries its Spanish and, where it differs, its Catalan wording.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Anything not recognised is an ordinary adult complaint.
DEFAULT_SPECIALTY = "general_practice"

#: How much a child marker is worth. Above any single symptom pattern: the
#: table never routes a child anywhere but paediatrics.
CHILD_WEIGHT = 6


def normalise(text: str) -> str:
    """Lower-cased, accent-folded, single-spaced — what every pattern matches."""
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", folded.lower())


@dataclass(frozen=True)
class RedFlag:
    """One published red flag: signals, and how many of them it takes.

    ``required`` names signals that must all be present; ``supporting`` are
    counted and ``min_supporting`` of them must hit. ``unless`` vetoes the
    flag — it is what keeps "bleeding between periods" out of the haemorrhage
    row.
    """

    id: str
    required: tuple[str, ...] = ()
    supporting: tuple[str, ...] = ()
    min_supporting: int = 0
    unless: tuple[str, ...] = ()

    def fires(self, text: str) -> bool:
        if any(re.search(p, text) for p in self.unless):
            return False
        if not all(re.search(p, text) for p in self.required):
            return False
        hits = sum(1 for p in self.supporting if re.search(p, text))
        return hits >= self.min_supporting


_BREATH = r"breath|breathe|breathing|respirar|respiracion|aliento|ahog|alenar|respira"
_MENSTRUAL = r"period|menstrua|regla|cycle|ciclo|smear|citologia"

#: The five published red flags. Each needs more than one signal, so a single
#: shared word never escalates a routine complaint.
RED_FLAGS: tuple[RedFlag, ...] = (
    RedFlag(
        # 1. Tight pain across the chest and struggling to catch their breath.
        id="chest_pain",
        required=(r"\bchest\b|pecho|\bpit\b|torax",),
        supporting=(_BREATH, r"tight|pain|dolor|opres|aprieta|presion|heavy"),
        min_supporting=1,
    ),
    RedFlag(
        # 2. Face droopy, arm gone weak, all of a sudden, words slurred.
        id="stroke",
        supporting=(
            r"face.{0,20}(droop|drop|fallen|gone down)|droopy|cara.{0,20}(caid|torcid)|"
            r"boca torcida|mig costat de la cara",
            r"arm.{0,25}(weak|gone|numb|dead)|brazo.{0,25}(debil|flojo|dormid|fuerza)|"
            r"bra.{0,25}(feble|adormit)",
            r"slur|words.{0,20}(slurred|jumbled)|habla.{0,25}(arrastr|cuesta|raro)|"
            r"no se le entiende|parla estrany",
            r"all of a sudden|suddenly|out of the blue|de repente|de golpe|de sobte",
        ),
        min_supporting=2,
    ),
    RedFlag(
        # 3. Cannot get their breath at all, came on out of nowhere.
        id="breathless",
        required=(
            r"(cannot|can ?not|can.?t|couldn.?t|struggling to|unable to).{0,25}"
            r"(get .{0,15}breath|breathe|catch .{0,15}breath)|"
            r"no (puede|puedo).{0,15}respirar|me ahogo|se ahoga|no me entra el aire|"
            r"falta de aire|no pot respirar",
        ),
    ),
    RedFlag(
        # 4. A cut bleeding heavily that will not stop after ten minutes.
        id="haemorrhage",
        required=(r"bleed|sangr|sagn|hemorrag",),
        supporting=(
            r"heavil|heavy|a lot of blood|mucha sangre|abundante|profus",
            r"(will|would|does) ?n.?t stop|not stop|no para|no deja de|no s.aturar|keeps bleeding",
            r"\bcut\b|wound|gash|corte|herida|tall\b",
        ),
        min_supporting=2,
        unless=(_MENSTRUAL,),
    ),
    RedFlag(
        # 5. Banged their head an hour ago, confused and being sick since.
        id="head_injury",
        required=(
            r"(bang|hit|knock|bump|struck|blow).{0,20}(the |their |his |her |my |a )?head|"
            r"head injury|golpe.{0,15}(en la )?cabeza|se (ha )?dado.{0,15}cabeza|"
            r"cop.{0,15}(al )?cap",
        ),
        supporting=(
            r"confus|not making sense|desorient|confundid|confos",
            r"being sick|been sick|vomit|throwing up|throw up|vomit|nausea|mareo",
            r"drowsy|sleepy|won.?t wake|somnolient|adormilad",
        ),
        min_supporting=1,
    ),
)

#: A child, however the caller says it. Catches the four paediatric rows.
CHILD_MARKERS: tuple[str, ...] = (
    r"\bchild\b|\bchildren\b|\bkid\b|\bkids\b|\bson\b|\bdaughter\b|\bbaby\b|\btoddler\b|"
    r"\binfant\b|little one|little boy|little girl|\bmy boy\b|\bmy girl\b|\bgrandson\b|"
    r"\bgranddaughter\b|\d+ (month|year)s? old|paediatric|pediatric",
    r"\bhij[oa]\b|\bnin[oa]\b|\bnen[a]?\b|\bbebe\b|\bcriatura\b|\bpeque\b|"
    r"\bmi chic[oa]\b|\bnietoa?\b|\bnieta\b|pediatr",
)

#: The published rows, as patterns. Each tuple is (specialty, weight, pattern),
#: and the weights only ever separate one published row from another.
SYMPTOM_PATTERNS: tuple[tuple[str, int, str], ...] = (
    # --- orthopaedics: the four injury rows ---------------------------------
    ("orthopaedics", 4, r"\bankle\b|tobillo|turmell"),
    ("orthopaedics", 3, r"went over on|twisted|rolled|me he torcido|se ha torcido|torcid"),
    ("orthopaedics", 4, r"\bknee\b|rodilla|genoll"),
    ("orthopaedics", 3, r"clicks|locks|gave way|giving way|se bloquea|falla|cruje|se dobla"),
    ("orthopaedics", 4, r"\bwrist\b|muneca|canell"),
    ("orthopaedics", 3, r"outstretched hand|onto (my|his|her|their) hand|caid[ao] .{0,15}mano"),
    ("orthopaedics", 4, r"\bshoulder\b|hombro|espatlla"),
    ("orthopaedics", 3, r"(cannot|can.?t|unable to) lift|no (puedo|puede) levantar|no aixeco"),
    (
        "orthopaedics",
        3,
        r"came off (my|his|her|their|a) bike|off the bike|caid[ao] de la bici|bici",
    ),
    ("orthopaedics", 3, r"slipped|resbal|relliscat|\bfell\b|\bfall\b|\bcaida\b"),
    ("orthopaedics", 2, r"sprain|fracture|esguince|fractura|roto|broken|swollen|hinchad|inflam"),
    # --- paediatrics: the symptoms the child rows pair with -----------------
    ("paediatrics", 2, r"pulling at (his|her|their|the) ear|tugging at .{0,10}ear|\bear\b|oido"),
    ("paediatrics", 2, r"barely slept|not sleeping|no duerme|apenas duerme"),
    ("paediatrics", 2, r"off (his|her|their) food|no come|sin apetito|not eating"),
    # --- gynaecology: the three rows ----------------------------------------
    ("gynaecology", 5, r"\bperiods?\b|menstrua|\breglas?\b|\bmenstruacion\b"),
    ("gynaecology", 4, r"smear|citologia|cervical"),
    ("gynaecology", 3, r"bleeding between|spotting|sangrado entre|manchado"),
    ("gynaecology", 3, r"heavy|abundante|irregular"),
    (
        "gynaecology",
        4,
        r"low(er)? down|lower abdomen|lower belly|pelvi|ovar|bajo vientre|"
        r"parte baja (del )?(vientre|abdomen)|ingle",
    ),
    ("gynaecology", 2, r"one side|un (lado|costat)|un lateral"),
    # --- general practice: the four unremarkable adult rows -----------------
    ("general_practice", 3, r"tired|run down|fatigue|exhaust|cansad|agotad|fatiga|cansament"),
    ("general_practice", 4, r"headache|head aches|migraine|dolor de cabeza|cefalea|mal de cap"),
    ("general_practice", 4, r"sore throat|throat|garganta|gola"),
    ("general_practice", 3, r"fever|feverish|temperature|fiebre|febril|febre|decimas"),
    ("general_practice", 4, r"dizzy|dizziness|light ?headed|mareo|maread|rodaments"),
    ("general_practice", 2, r"blood pressure|tension( arterial)?|presion arterial"),
    ("general_practice", 2, r"prescription|receta|repeat medication"),
)

#: Which specialty a child's complaint is *not* allowed to override. Nothing
#: published sends a child anywhere but paediatrics.
_CHILD_SPECIALTY = "paediatrics"


def red_flag(complaint: str) -> str | None:
    """The id of the published red flag this complaint is, or ``None``."""
    text = normalise(complaint)
    for flag in RED_FLAGS:
        if flag.fires(text):
            return flag.id
    return None


def mentions_child(complaint: str) -> bool:
    text = normalise(complaint)
    return any(re.search(p, text) for p in CHILD_MARKERS)


def score(complaint: str) -> dict[str, int]:
    """What each specialty scored. Exposed so a wrong route can be explained."""
    text = normalise(complaint)
    totals: dict[str, int] = {}
    for specialty, weight, pattern in SYMPTOM_PATTERNS:
        if re.search(pattern, text):
            totals[specialty] = totals.get(specialty, 0) + weight
    if any(re.search(p, text) for p in CHILD_MARKERS):
        totals[_CHILD_SPECIALTY] = totals.get(_CHILD_SPECIALTY, 0) + CHILD_WEIGHT
    return totals


def route(complaint: str) -> str:
    """The specialty the published table sends this complaint to."""
    totals = score(complaint)
    if not totals:
        return DEFAULT_SPECIALTY
    best = max(totals.values())
    winners = sorted(s for s, total in totals.items() if total == best)
    # A tie is the table being ambiguous about a paraphrase; the residue wins.
    if len(winners) > 1 and DEFAULT_SPECIALTY in winners:
        return DEFAULT_SPECIALTY
    return winners[0]
