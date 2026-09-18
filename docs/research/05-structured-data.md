# Research 05 — Noisy speech transcripts to exact structured data

Date: 2026-09-19. Target: Python 3.12, pipecat-ai 1.11, Soniox STT, OpenAI-compatible LLM with tool calls.
PyPI versions and dates come from the PyPI JSON API on 2026-09-19. Hands-on results come from a scratch venv (Python 3.12.12) on this machine.

## Summary

- Use `python-stdnum` (2.2, LGPL) for DNI/NIE. Generate 1-edit digit candidates from STT confusions and keep the one whose check letter matches. Tested: 0 ambiguous cases in 2000 random ids at 1 edit; 2 edits produce false positives.
- Surnames: fold accents, then apply a small Spanish confusion map (b/v, c/s/z, ll/y, silent h) before exact match. Fall back to `rapidfuzz` (3.14.6, MIT). "Sáez" vs "Sáenz" stay distinct under folding (Levenshtein 1), so the agent must ask "¿Sáez o Sáenz?" and use the specialty as the tiebreaker.
- Dictated email/phone/id: a 20-line spoken-form mapper plus `text2num` (3.1.0, MIT), `email-validator` (2.3.0, Unlicense) and `phonenumbers` (9.0.39, Apache-2.0). All three passed the dictation tests. NeMo ITN is heavy (pynini, no pip on macOS) and not worth it here.
- Dates: no Python library handles the full colloquial Spanish set. `dateparser` 1.4.3 returned None for "pasado mañana", "el jueves que viene", "en quince días" and "this coming Thursday". Microsoft Recognizers-Text (2019 alpha) handles most Spanish forms but needs `emoji<2` and fails on "in a fortnight". Resolve dates with the LLM plus a deterministic `resolve_date` tool that does the arithmetic with `python-dateutil` and `holidays` (0.104, MIT, subdiv MD).
- Geocoding: CartoCiudad (IGN, free, no key, EUPL-1.2) returned portal-level coordinates for "Calle Alcalá 200" and tolerated the misspelling "alcla". Nominatim returned nothing for the misspelling and caps at 1 req/s. Pick CartoCiudad first, Nominatim/Photon as fallback, `haversine` (2.9.0, MIT) for distance.
- LLM side: use `strict: true` tool schemas with enums for closed lists (specialty, insurer, site). Do not use outlines/xgrammar unless you serve the model yourself; vLLM already uses xgrammar by default. Triage: a static-embedding prototype (model2vec, 0.4 ms) misclassified 2 of 6 sentences, so use a rules list plus LLM enum, with red flags as regex first.

## Library table

| Need | Library (PyPI) | Version + date | License | Verdict | URL |
|---|---|---|---|---|---|
| DNI/NIE/CIF validation | python-stdnum | 2.2, 2026-01-04 | LGPL-2.1+ | Use. `stdnum.es.dni/nie/nif`, `calc_check_digit`. | https://pypi.org/project/python-stdnum/ |
| Fuzzy string match | rapidfuzz | 3.14.6, 2026-08-30 | MIT | Use. 2000-name directory in ~1 ms. | https://pypi.org/project/rapidfuzz/ |
| Phonetic codes | jellyfish | 1.2.1, 2025-10-11 | MIT | Optional. English-tuned Metaphone/NYSIIS; keep for second opinion only. | https://pypi.org/project/jellyfish/ |
| Levenshtein (C) | Levenshtein / python-Levenshtein | 0.27.5, 2026-09-12 | GPL-2.0-or-later | Avoid. GPL and rapidfuzz already ships `rapidfuzz.distance.Levenshtein`. | https://pypi.org/project/Levenshtein/ |
| Per-pair edit costs | weighted-levenshtein | 0.2.2, 2023-01-31 | MIT | Optional. Cheap b/v, s/z costs. Needs numpy. | https://pypi.org/project/weighted-levenshtein/ |
| Phonetic (many algos) | abydos | 0.5.0, 2020-01-11 | GPL-3.0+ | Avoid. Declares Python 3.5-3.8, dead since 2020. Has Spanish Metaphone and Beider-Morse but GPL and unmaintained. | https://pypi.org/project/abydos/ |
| Phonetic (small) | pyphonetics | 0.5.3, 2020-02-25 | MIT | Skip. Soundex/Metaphone/MRA only, English rules. | https://pypi.org/project/pyphonetics/ |
| Double Metaphone | Metaphone | 0.6, 2016-08-24 | BSD | Skip. Old; jellyfish covers it. | https://pypi.org/project/Metaphone/ |
| Spanish Metaphone | amsqr/Spanish-Metaphone (GitHub, not on PyPI) | 2011 script | BSD-2 | Vendor if you want a phonetic code; a hand-written fold is simpler. | https://github.com/amsqr/Spanish-Metaphone |
| G2P to IPA | epitran | 1.35.2, 2026-06-18 | MIT-Modern-Variant | Optional. `spa-Latn` needs no Flite. Overkill for a 30-name directory. | https://pypi.org/project/epitran/ |
| G2P (espeak) | phonemizer | 3.4.0, 2026-07-31 | GPL-3.0+ | Avoid. GPL plus espeak-ng system dependency. | https://pypi.org/project/phonemizer/ |
| Accent folding | Unidecode | 1.4.0, 2025-04-24 | GPL-2.0+ | Works, but GPL. Use `unicodedata.normalize("NFKD")` or anyascii instead. | https://pypi.org/project/Unidecode/ |
| Accent folding | anyascii | 0.3.3, 2025-06-29 | ISC | Use if you want a lib; stdlib NFKD is enough for Spanish. | https://pypi.org/project/anyascii/ |
| Spoken numbers to digits | text2num | 3.1.0, 2026-08-21 | MIT | Use. `alpha2digit(text, "es")`. No Spanish ordinals. | https://pypi.org/project/text2num/ |
| Digits to words | num2words | 0.5.14, 2024-12-17 | LGPL | Use for read-back TTS if needed ("veintitrés"). | https://pypi.org/project/num2words/ |
| Spoken numbers (es) | word2number-es | 1.0.1, 2023-01-13 | MIT | Skip. text2num is maintained and better. | https://pypi.org/project/word2number-es/ |
| Email syntax | email-validator | 2.3.0, 2025-08-26 | Unlicense | Use. `check_deliverability=False` on the hot path. | https://pypi.org/project/email-validator/ |
| DNS for email | dnspython | 2.8.0, 2025-09-07 | ISC | Only if you enable the MX check. | https://pypi.org/project/dnspython/ |
| Phone parse/format | phonenumbers | 9.0.39, 2026-09-10 | Apache-2.0 | Use. `parse(raw, "ES")`, E.164. | https://pypi.org/project/phonenumbers/ |
| ITN (WFST) | nemo_text_processing | 1.2.0, 2026-06-05 | Apache-2.0 | Skip. Spanish ITN exists, but pynini blocks pip on macOS/Windows. | https://pypi.org/project/nemo_text_processing/ |
| Whisper normalizer | whisper-normalizer | 0.1.15, 2026-07-26 | MIT | Skip. Only `BasicTextNormalizer` for Spanish; it strips, it does not convert. | https://pypi.org/project/whisper-normalizer/ |
| Natural dates | dateparser | 1.4.3, 2026-09-03 | BSD-3-Clause | Partial. Fails weekday phrases and Spanish idioms (tested). | https://pypi.org/project/dateparser/ |
| Natural dates (en) | parsedatetime | 2.6, 2020-05-31 | Apache-2.0 | Partial. Gets "this coming Thursday" right, breaks on "fortnight" and "the twelfth of October". | https://pypi.org/project/parsedatetime/ |
| Natural dates (es) | recognizers-text-date-time | 1.0.2a2, 2019-11-12 | MIT | Fallback only. Works on 3.12 with `emoji<2`. Alpha, 2019. | https://pypi.org/project/recognizers-text-date-time/ |
| Duckling | rasa/duckling (Docker), duckling PyPI 1.8.0 (2018) | image; PyPI pkg dead | BSD-3 (Haskell lib) | Skip. Extra container; Docker daemon was not running here, so untested (UNVERIFIED). | https://hub.docker.com/r/rasa/duckling |
| Date arithmetic | python-dateutil | 2.9.0.post0, 2024-03-01 | Apache-2.0 / BSD | Use. `relativedelta(weekday=TH(+1))`. | https://pypi.org/project/python-dateutil/ |
| Public holidays | holidays | 0.104, 2026-09-07 | MIT | Use. `country_holidays("ES", subdiv="MD")`. | https://pypi.org/project/holidays/ |
| Public holidays | workalendar | 17.0.0, 2023-01-01 | MIT | Skip. Stale vs holidays. | https://pypi.org/project/workalendar/ |
| Geocoder clients | geopy | 2.5.0, 2026-07-12 | MIT | Use for Nominatim/Photon fallback and `geopy.distance`. | https://pypi.org/project/geopy/ |
| Haversine | haversine | 2.9.0, 2024-11-28 | MIT | Use. One function, no deps. | https://pypi.org/project/haversine/ |
| Constrained decoding | outlines | 1.3.3, 2026-08-06 | Apache-2.0 | Only for self-hosted models. | https://pypi.org/project/outlines/ |
| Constrained decoding | lm-format-enforcer | 0.11.3, 2025-08-24 | MIT | Only for self-hosted models. | https://pypi.org/project/lm-format-enforcer/ |
| Constrained decoding | xgrammar | 0.2.7, 2026-09-15 | Apache-2.0 | vLLM default backend; nothing to install client-side. | https://pypi.org/project/xgrammar/ |
| Schema + validation | pydantic | 2.13.5, 2026-08-28 | MIT | Use. Generate tool JSON schema, validate tool args. | https://pypi.org/project/pydantic/ |
| Structured LLM client | instructor | 1.17.0, 2026-09-09 | MIT | Optional. Adds retries on validation failure. | https://pypi.org/project/instructor/ |
| Embeddings | sentence-transformers | 6.1.0, 2026-09-18 | Apache-2.0 | Not needed for 15 phrases. Pulls torch. | https://pypi.org/project/sentence-transformers/ |
| Embeddings (bge-m3) | FlagEmbedding | 1.4.2, 2026-08-24 | MIT | Not needed. bge-m3 is 1024-dim, 100+ languages, MIT. | https://pypi.org/project/FlagEmbedding/ |
| Static embeddings | model2vec | 0.9.0, 2026-08-12 | MIT | Tested. Fast (0.4 ms) but wrong on 2/6 triage sentences. | https://pypi.org/project/model2vec/ |
| Voice pipeline | pipecat-ai | 1.11.0, 2026-09-18 | BSD-2-Clause | Given. `FunctionSchema` + `register_function`. | https://pypi.org/project/pipecat-ai/ |

## 1. Spanish ID validation

DNI: 8 digits plus a letter. Letter = `"TRWAGMYFPDXBNJZSQVHLCKE"[int(digits) % 23]`. NIE: X/Y/Z prefix maps to 0/1/2, then the same rule. `stdnum.es.nif` accepts both.

Tested on this machine:

```python
from stdnum.es import dni, nie, nif

dni.calc_check_digit("12345678")  # 'Z'
dni.is_valid("12345678A")  # False
nie.is_valid("X1234567L")  # True
nif.is_valid("X1234567L")  # True (accepts DNI and NIE)
```

The check letter carries log2(23) ≈ 4.5 bits. Use it to pick between STT candidates.

```python
import itertools
from stdnum.es import dni

CONF = {
    "6": "7",
    "7": "6",
    "0": "8",
    "8": "0",
    "1": "7",
    "5": "6",
}  # seis/siete, ocho/cero, uno/siete


def resolve_dni(digits: str, letter: str) -> list[str]:
    cands = [digits] + [
        "".join(digits[:i] + CONF[c] + digits[i + 1 :]) for i, c in enumerate(digits) if c in CONF
    ]
    return [c for c in dict.fromkeys(cands) if dni.calc_check_digit(c) == letter.upper()]


resolve_dni("72345678", "Z")  # ['72345778'] -> exactly one 1-edit candidate fits
```

Measured: with 1 substitution, 0.0% of 2000 random ids had more than one valid candidate. With 2 substitutions, false positives appear ("12345678"+Z also matched "72345778"). Rule: allow one edit. If zero or more than one candidate fits, ask the caller to repeat the digits in pairs.

Ask for the letter explicitly ("¿y la letra?"). Map spoken letter names: "zeta"→Z, "uve"→V, "be"→B, "ka"→K, "equis"→X, "i griega"→Y, "hache"→H. "be" and "de" and "pe" collide acoustically; confirm B/D/P with a word ("¿be de Barcelona?").

## 2. Surname matching

Hands-on results (directory of 16 surnames, folded with NFKD):

| Heard | rapidfuzz WRatio top-2 | Spanish fold equal |
|---|---|---|
| Saez | Sáez 100, Sáenz 89 | Sáez |
| Saenz | Sáenz 100, Sáez 89 | Sáenz |
| Giménes | Giménez 86, Jiménez 71 | Jiménez, Giménez |
| Basques | Bazquez 71, Vázquez 57 | Vázquez, Bazquez |
| Ernandez | Hernández 94, Fernández 94 | Hernández |
| Sevallos | Cevallos 88, Ceballos 75 | Ceballos, Zeballos, Cevallos |

Findings:

- Accent folding plus a Spanish confusion fold solves b/v, c/s/z, ll/y, g/j, silent h. Metaphone (English rules) gives "FSKS" vs "BSKS" for Vázquez/Bazquez, so it does not merge b/v. Do not rely on English phonetic codes.
- "Sáez" vs "Sáenz" differ by one real consonant. Every metric keeps them apart (Levenshtein 1, Jaro-Winkler 0.95, Soundex S200 vs S520). That is correct: they are different people. The fix is dialog, not matching. When the top-2 candidates are within distance 1, ask a disambiguating question that includes the specialty: "¿La doctora Sáenz, de pediatría, o el doctor Sáez, de medicina general?".
- Feed the whole provider directory to Soniox as `context.terms` (max 8,000 tokens). Soniox v5 models advertise "more robust context usage for names". This cuts the error before it reaches Python.
- rapidfuzz `process.extract` over 2000 names took 1.06 ms. Latency is not a concern.

```python
import re, unicodedata
from rapidfuzz import process, fuzz


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("h", "").replace("v", "b").replace("ll", "y").replace("qu", "k")
    s = re.sub(r"c([ei])", r"s\1", s).replace("z", "s")
    s = re.sub(r"c([aou])", r"k\1", s)
    s = re.sub(r"g([ei])", r"j\1", s)
    return re.sub(r"(.)\1", r"\1", s)


def match_provider(heard: str, directory: dict[str, str]) -> list[tuple[str, float]]:
    keys = {fold(n): n for n in directory}  # directory: surname -> specialty
    if fold(heard) in keys:
        return [(keys[fold(heard)], 100.0)]
    hits = process.extract(fold(heard), list(keys), scorer=fuzz.WRatio, limit=3)
    return [(keys[k], s) for k, s, _ in hits if s >= 80]  # >1 hit within 10 points -> ask
```

Weighted Levenshtein (per-pair costs) is a valid alternative: `lev("vazquez","bazquez")` = 0.2 with b/v cost 0.2. It adds numpy; the fold above gets the same effect without it.

epitran (`spa-Latn`) converts both sides to IPA and then you compare IPA strings. It is correct but adds a dependency for no gain at directory sizes under 100.

## 3. Dictated text: email, phone, numbers

Tested mapper plus validator:

```python
from email_validator import validate_email

SPOKEN = {
    " arroba ": "@",
    " punto ": ".",
    " guion bajo ": "_",
    " guión bajo ": "_",
    " guion ": "-",
    " at ": "@",
    " dot ": ".",
    " underscore ": "_",
    " dash ": "-",
    " hyphen ": "-",
}


def spoken_to_email(s: str) -> str:
    s = f" {s.lower().strip()} "
    for k, v in SPOKEN.items():
        s = s.replace(k, v)
    return s.replace(" ", "")


e = spoken_to_email("ana punto garcia arroba gmail punto com")  # ana.garcia@gmail.com
validate_email(e, check_deliverability=False).normalized  # ok; turn DNS on only off the hot path
```

Also normalize domain aliases the STT may spell out: "gmail punto com", "yimeil", "jotmail" → gmail.com, hotmail.com. Keep a 10-entry table of Spanish domains (gmail.com, hotmail.com, hotmail.es, outlook.es, yahoo.es, icloud.com, telefonica.net).

Phone: `phonenumbers.parse("612 34 56 78", "ES")` → +34612345678, valid, mobile. Landline "91 123 45 67" → +34911234567. Spaniards dictate mobiles as 3+2+2+2 groups; text2num already produces "612 34 56 78" from "seiscientos doce treinta y cuatro cincuenta y seis setenta y ocho". Join the digits and parse.

Numbers: `alpha2digit("uno dos tres cuatro cinco seis siete ocho zeta", "es")` → "1 2 3 4 5 6 7 8 zeta". `alpha2digit("nací el veintitrés de marzo de mil novecientos ochenta y cinco", "es")` → "nací el 23 de marzo de 1985". Spanish ordinals are not supported; that only matters for "primero de mayo" style dates.

Soniox v5 claims "better alphanumeric recognition and formatting for numbers, dates, times, emails, IDs, codes". Expect digits already formatted most of the time; keep text2num as the safety net.

NeMo ITN supports Spanish (TN, ITN, audio-based). It needs pynini; pip install is unsupported on macOS and Windows. Not worth it for six fields. whisper-normalizer offers only `BasicTextNormalizer` for Spanish (lowercase, strip punctuation); it does not convert words to digits.

Read-back pattern (Vapi, Twilio, LiveKit guides agree): collect one field per turn, read back exact fields (name spelling, email, id), confirm, move on. On a "no", spell the value back once, letter by letter, then re-ask. Batch a final confirmation. Never read back id or phone in this project (privacy rule); confirm them by the last two digits only or by "¿correcto?" after the caller repeats.

## 4. Dates

Base for all tests: Thursday 2026-09-17 10:00 Europe/Madrid.

| Phrase | dateparser 1.4.3 | parsedatetime 2.6 | Recognizers-Text 1.0.2a2 | Expected |
|---|---|---|---|---|
| this coming Thursday | None | Thu 09-24 | 09-24 | 09-24 |
| Thursday (PREFER future) | Thu 09-24 | Thu 09-24 | 09-10 or 09-17 (ambiguous) | 09-24 |
| in a fortnight | None | wrong (returns base) | crash (AttributeError) | 10-01 |
| first thing on Monday the twelfth of October | None | wrong (10-01) | splits: "monday" + "twelfth of october" 2026-10-12 | 10-12 08:00-ish |
| pasado mañana | None | n/a | 09-19 | 09-19 |
| el jueves que viene | None | n/a | 09-10 or 09-17 (ignores "que viene") | 09-24 |
| el próximo jueves | None | n/a | 09-24 | 09-24 |
| en quince días | None | n/a | range 09-18..10-03 | 10-02 (or 10-01) |
| de hoy en ocho | None | n/a | only "hoy" | 09-24 |
| la semana que viene | None | n/a | wrong range (09-01..10-01) | week of 09-21 |
| dentro de dos semanas | None | n/a | range 09-18..10-02 | 10-01 |
| en 15 días / dentro de 2 semanas (digits) | ok | n/a | ok | ok |

Conclusions:

- dateparser's Spanish data lacks "pasado mañana", "que viene", "de hoy en ocho", "quincena" (checked in `dateparser/data/date_translation_data/es.py`). It also returns None for "next Thursday" in English. Do not depend on it for this problem.
- Recognizers-Text is the best rule engine for Spanish, but it is a 2019 alpha. It installs on 3.12 only with `emoji<2` and prints SyntaxWarnings. It returns two candidates for bare weekdays, which you must post-filter to the future one.
- Duckling supports Time, Duration, Numeral, Ordinal for Spanish (`Duckling/Dimensions/ES.hs`). It needs a Haskell server or the `rasa/duckling` Docker image. The Docker daemon was down here; its handling of "de hoy en ocho" is UNVERIFIED.
- Recommended: let the LLM extract a small structured intent, and let Python do the arithmetic. This keeps determinism where it matters (weekday math, timezone, closures).

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR, SA, SU
import holidays

MADRID = ZoneInfo("Europe/Madrid")
WD = [MO, TU, WE, TH, FR, SA, SU]
ES_MD = holidays.country_holidays("ES", subdiv="MD", years=range(2026, 2028))


def resolve_date(
    now: datetime,
    kind: str,
    n: int = 0,
    weekday: int | None = None,
    day: int | None = None,
    month: int | None = None,
) -> datetime:
    """kind: today|tomorrow|day_after_tomorrow|in_days|in_weeks|next_weekday|explicit"""
    d = now.astimezone(MADRID).replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "tomorrow":
        return d + timedelta(days=1)
    if kind == "day_after_tomorrow":
        return d + timedelta(days=2)
    if kind == "in_days":
        return d + timedelta(days=n)  # "en quince días" -> n=15
    if kind == "in_weeks":
        return d + timedelta(weeks=n)  # "de hoy en ocho" -> n=1, fortnight -> 2
    if kind == "next_weekday":  # always strictly after today
        return d + relativedelta(days=+1, weekday=WD[weekday](+1))
    if kind == "explicit":
        cand = d.replace(day=day, month=month)
        return cand if cand > d else cand.replace(year=d.year + 1)
    return d


def is_closed(d: datetime, clinic_closures: set) -> str | None:
    if d.weekday() == 6:
        return "sunday"
    if d.date() in ES_MD:
        return ES_MD.get(d.date())
    if d.date() in clinic_closures:
        return "clinic closure"
    return None
```

Tool schema for the LLM: `{"kind": enum, "n": int|null, "weekday": 0-6|null, "day": int|null, "month": int|null, "time_pref": "first_thing"|"morning"|"afternoon"|null}`. The prompt states the rule: "el jueves que viene / this coming Thursday / next Thursday means the next Thursday strictly after today, even if today is Thursday. En quince días = 15 days. De hoy en ocho = 7 days. Una quincena / a fortnight = 14 days. A primera hora = first slot of the day." Give the LLM `now` in Madrid time and the weekday name in the system prompt on every turn.

holidays 0.104 for ES/MD 2026 returned: 01-01, 01-06, 04-02, 04-03, 05-01, 05-02 (Madrid Day), 08-15, 10-12, 11-02 (Monday after All Saints), 12-07 (Monday after Constitution Day), 12-08, 12-25. Madrid city local holidays (San Isidro 05-15, Almudena 11-09) are not in the MD subdivision set. Add them by hand if the clinic follows the city calendar.

## 5. Geocoding Madrid addresses

Live probes on 2026-09-19:

| Service | "Calle de Alcalá 200, Madrid" | Misspelled "calle alcla 200 madrid" | Suburb "Avenida de Europa 10, Pozuelo" |
|---|---|---|---|
| CartoCiudad candidates | portal, 40.43029 / -3.66386, CP 28028 | same portal, correct | portal, 40.43559 / -3.79782, CP 28224 |
| Nominatim | house 200, 40.43031 / -3.66375 | [] (no result) | not tested |
| Photon | house 200, 40.43031 / -3.66375 | not tested | not tested |

CartoCiudad (IGN, official):

- Endpoint: `https://www.cartociudad.es/geocoder/api/geocoder/candidates?q=<text>&limit=3`. Portals return `lat`, `lng`, `type="portal"`, `muni`, `postalCode`, `refCatastral` directly since the August 2024 update (no second `find` call).
- Filters: `municipio_filter=Madrid`, `provincia_filter=Madrid`, `cod_postal_filter`, `no_process=municipio,provincia,toponimo` to drop non-street hits. Names must match CartoCiudad spelling.
- Free, no key, no documented rate limit. Service code is EUPL-1.2. Tolerates a missing letter in the street name (fuzzy). Filter results to `type in {"portal","callejero"}` and `province == "Madrid"`.
- Traps: `state != 0` means the portal is approximate; "dosientos" as a spelled number returned nothing, so run text2num first.

Nominatim: 1 request/second hard cap, custom User-Agent mandatory, results must be cached, no autocomplete. Fine as a fallback for a demo, not as the primary path. Photon (komoot) has no published limit; "if you have to ask, run your own instance".

Google Geocoding: 10,000 free events per month, then $5.00 per 1,000. Rate limit 3,000 QPM. Mapbox Temporary Geocoding: 100,000 free per month, then $0.75 per 1,000; storing results requires the Permanent tier at $5.00 per 1,000. Both need a key and billing. Not needed when CartoCiudad works.

Madrid open data publishes the official "Callejero" with portal coordinates (datos.madrid.es). Useful for an offline index, but CartoCiudad covers suburbs too. UNVERIFIED which file format and CRS the current export uses.

```python
import httpx
from haversine import haversine

SITES = {
    "Centro": (40.4168, -3.7038),
    "Chamartín": (40.4600, -3.6760),
    "Pozuelo": (40.4356, -3.7978),
}


async def geocode(q: str, client: httpx.AsyncClient) -> tuple[float, float] | None:
    r = await client.get(
        "https://www.cartociudad.es/geocoder/api/geocoder/candidates",
        params={"q": q, "limit": 5, "no_process": "municipio,provincia,toponimo"},
        timeout=5,
    )
    hits = [
        h
        for h in r.json()
        if h.get("type") in ("portal", "callejero") and h.get("province") == "Madrid"
    ]
    return (hits[0]["lat"], hits[0]["lng"]) if hits else None


def nearest_site(point):
    return min(SITES, key=lambda s: haversine(point, SITES[s]))
```

Spoken-address tips: strip "número" and "calle de" variants, run text2num first, append "Madrid" when the caller omits the town, and read back the street plus number before geocoding. When CartoCiudad returns more than one municipality, ask "¿en Madrid capital o en Pozuelo?".

## 6. LLM-side techniques

Structured tool calls:

- OpenAI-compatible `strict: true` on the function definition: every property in `required`, `additionalProperties: false`, optional fields typed `["string","null"]`. Use `enum` for specialty, insurer, site, date `kind`. Force a tool with `tool_choice: {"type":"function","name":...}` on extraction turns.
- vLLM structured outputs use backend `auto` (xgrammar first, guidance as alternative). `response_format: {"type":"json_schema"}` and `extra_body: {"structured_outputs": {...}}` both work. If the team self-hosts (the qwen/deepseek bench on the VPS), nothing extra to install. outlines and lm-format-enforcer only matter for local `transformers`/llama.cpp runs.
- pipecat: `FunctionSchema(name, description, properties, required, handler=...)` inside `ToolsSchema`, or `llm.register_function(name, handler)`. Docs do not mention `strict`; pass it through the OpenAI service's tool dict and verify the provider honours it. UNVERIFIED for pipecat 1.11 whether `strict` survives serialization for non-OpenAI providers.
- pydantic 2.13 generates the schema; validate tool args with `Model.model_validate(args)` before writing to the DB. instructor 1.17 adds automatic retry with the validation error in the prompt.

Candidates with confidence: ask the model to return `{"value": ..., "alternatives": [...], "confidence": "high"|"low"}`. Treat "low" as "confirm before saving". Pair it with the check letter for ids and with the directory for surnames.

Dual extraction (two models vote) adds latency and cost. Prefer one strict tool call plus a deterministic validator (check letter, email syntax, phone validity, directory lookup). Vote only on surnames if both a fast and a slow model are already in the pipeline.

Papers on ASR error correction with LLMs (relevant ideas, not drop-in code):

- Phonetic retrieval-based augmentation (Apple, arXiv 2409.15353, 2024): detect the entity, retrieve phonetically similar names from the directory, feed them to the LLM, decode again. Named-entity error rate −73.6%. This is the pattern for the provider directory: put candidate names into the prompt.
- GER for rare words with synthetic data and phonetic context (Interspeech 2025, arXiv 2505.17410): N-best plus phonetic context reduces over-correction.
- ClozeGER (ACL 2024, arXiv 2405.10025): only the spans that differ across N-best become blanks; the LLM fills them. Soniox does not expose N-best in the streaming API (UNVERIFIED), so emulate it with the check letter and directory.
- ProGRes (SLT 2024, arXiv 2409.00217): prompted rescoring on N-best gives 5-25% WER gain. Needs N-best with scores.
- Contextual biasing surveys (arXiv 2512.21828, 2604.12398, 2505.19179): the industry direction is retrieval of hotwords plus LLM-ASR. Soniox `context.terms` is the productized version; use it.

## 7. Symptom to specialty

Measured with model2vec `potion-multilingual-128M` (static embeddings distilled from bge-m3), prototypes from 2-3 example sentences per class:

| Sentence | Predicted | Right? |
|---|---|---|
| me duele mucho la rodilla desde que corrí | traumatología 0.67 | yes |
| tengo un sarpullido en la espalda | traumatología 0.55 | no (dermatología) |
| mi niña tiene tos y fiebre | pediatría 0.55 | yes |
| me aprieta el pecho y me sudan las manos | urgencias 0.36 | yes, but low margin |
| se me ha quedado la cara dormida de repente | otorrino 0.27 | no (red flag: stroke) |
| no oigo bien del oído izquierdo | otorrino 0.41 | yes |

Encoding six sentences took 0.4 ms. Model load took 90 s on first download (250 MB). Accuracy is the problem, not latency: 2 of 6 wrong, and a red flag missed. A transformer model (paraphrase-multilingual-MiniLM-L12-v2, 0.1B params, 384-dim, Apache-2.0) would do better, but still needs labelled examples per class and a threshold, and pulls torch into the pipecat process.

Recommendation for 15 phrases plus 5 red flags:

1. Red flags first, as a regex list in Spanish and English, before any model. "dolor en el pecho", "no puedo respirar", "cara dormida", "habla rara", "sangrado abundante", "pérdida de conocimiento". A hit escalates and ends the triage.
2. Then a keyword/synonym table per specialty (piel, sarpullido, lunar → dermatología; rodilla, tobillo, espalda → traumatología; niño, bebé, hijo → pediatría). This is deterministic, testable, and covers the scored list.
3. Then the LLM with a strict enum tool as the general fallback. The prompt lists the specialties and the rule for children (age < 14 → pediatría).
4. Unit-test the 20 scored sentences against steps 1-3. Add an embedding model only if the tests show gaps that rules cannot close.

## Recommendation per problem

The New Patient: one field per turn. Names: fold and match against nothing (free text), read back letter by letter only when the caller confirms a rare spelling. Surnames: keep both. DNI/NIE: text2num → digits, letter word → letter, `resolve_dni` with 1-edit candidates, `stdnum.es.nif.validate`; on failure ask again in pairs. Date of birth: text2num, then `datetime(y, m, d)` with year sanity (1920-2026). Phone: phonenumbers, region ES, require `is_valid_number`. Email: spoken mapper, domain alias table, email-validator without DNS, read back as "ana punto garcia arroba gmail punto com". Insurer: strict enum in the tool schema. Feed insurer names and provider surnames to Soniox `context.terms`.

The Doctor and the Site: provider directory in Soniox context. `match_provider` with fold; when top-2 are within 10 points or Levenshtein ≤1, ask with specialties. After the match, check leave and site-day rules in Python, never in the prompt. Answer with the alternative (other day at that site, or other site that day).

When Exactly: LLM emits `resolve_date` intent; Python computes the date in Europe/Madrid with dateutil, `holidays` ES/MD plus the clinic closure list, then proposes the next open slot. Read back the full date with weekday ("el jueves 24 de septiembre"). Skip dateparser.

The Nearest Site: text2num on the address, CartoCiudad `candidates` with `no_process` filter, Nominatim via geopy as fallback with a custom User-Agent, haversine to the published site coordinates. Cache results by normalized query.

Adversarial and Privacy: a Python guard on every outgoing text frame: normalize (strip spaces, hyphens, dots), then substring-check every stored `national_id` and `phone`, plus their digit-only and spaced variants. Block the frame and replace with a safe sentence. Never pass ids into the LLM context if you can avoid it; keep them in session state referenced by a placeholder.

Triage: red-flag regex → keyword table → LLM strict enum. No embedding model in v1.

## Sources

- https://pypi.org/project/python-stdnum/ — python-stdnum 2.2, 2026-01-04, LGPL.
- https://github.com/arthurdejong/python-stdnum/blob/master/stdnum/es/dni.py — DNI mod-23 letter table "TRWAGMYFPDXBNJZSQVHLCKE", `calc_check_digit`, `validate`.
- https://arthurdejong.org/python-stdnum/doc/1.17/stdnum.es.dni — docs for DNI module.
- https://arthurdejong.org/python-stdnum/doc/1.8/stdnum.es.nie — NIE module: X/Y/Z prefix, same check letter.
- https://pypi.org/project/rapidfuzz/ — rapidfuzz 3.14.6, 2026-08-30, MIT.
- https://pypi.org/project/jellyfish/ — jellyfish 1.2.1, 2025-10-11, MIT.
- https://jamesturk.github.io/jellyfish/functions/ — jellyfish functions (Metaphone, NYSIIS, MRA, Damerau-Levenshtein).
- https://pypi.org/project/Levenshtein/ — Levenshtein 0.27.5, 2026-09-12, GPL-2.0-or-later.
- https://pypi.org/project/weighted-levenshtein/ — 0.2.2, 2023-01-31, MIT; per-pair substitution cost matrix.
- https://pypi.org/project/abydos/ — abydos 0.5.0, 2020-01-11, GPL-3.0+.
- https://github.com/chrislit/abydos — README says Python 3.5-3.8; has Spanish Metaphone and Beider-Morse; inactive.
- https://pypi.org/project/pyphonetics/ — 0.5.3, 2020-02-25, MIT.
- https://github.com/Lilykos/pyphonetics — Soundex, Metaphone, Refined/Fuzzy Soundex, Lein, MRA.
- https://pypi.org/project/Metaphone/ — Metaphone 0.6, 2016-08-24, BSD (Double Metaphone).
- https://github.com/amsqr/Spanish-Metaphone — Spanish Metaphone script, BSD-2, 2011, not on PyPI.
- https://www.researchgate.net/publication/285589803_Comparison_of_a_Modified_Spanish_Phonetic_Soundex_and_Phonex_coding_functions_during_data_matching_process — Spanish phonetic coding vs Soundex for record matching.
- https://pypi.org/project/epitran/ — epitran 1.35.2, 2026-06-18, MIT-Modern-Variant.
- https://github.com/dmort27/epitran — `spa-Latn` supported, no Flite needed for Spanish.
- https://pypi.org/project/phonemizer/ — phonemizer 3.4.0, 2026-07-31, GPL-3.0+.
- https://pypi.org/project/Unidecode/ — Unidecode 1.4.0, 2025-04-24, GPL-2.0+.
- https://pypi.org/project/anyascii/ — anyascii 0.3.3, 2025-06-29, ISC.
- https://pypi.org/project/text2num/ — text2num 3.1.0, 2026-08-21, MIT; module name `text_to_num`.
- https://github.com/allo-media/text2num — Spanish `alpha2digit`, no Spanish ordinals.
- https://pypi.org/project/num2words/ — num2words 0.5.14, 2024-12-17, LGPL.
- https://pypi.org/project/word2number-es/ — 1.0.1, 2023-01-13, MIT.
- https://pypi.org/project/email-validator/ — email-validator 2.3.0, 2025-08-26, Unlicense.
- https://github.com/JoshData/python-email-validator — `check_deliverability`, `normalized`, dnspython for DNS.
- https://pypi.org/project/dnspython/ — dnspython 2.8.0, 2025-09-07, ISC.
- https://pypi.org/project/phonenumbers/ — phonenumbers 9.0.39, 2026-09-10, Apache-2.0.
- https://pypi.org/project/nemo_text_processing/ — nemo_text_processing 1.2.0, 2026-06-05, Apache-2.0.
- https://github.com/NVIDIA/NeMo-text-processing — pynini dependency; pip unsupported on macOS/Windows.
- https://docs.nvidia.com/nemo-framework/user-guide/25.09/nemotoolkit/nlp/text_normalization/wfst/wfst_text_normalization.html — language table: es supports TN and ITN.
- https://arxiv.org/abs/2104.05055 — NeMo ITN paper (WFST design).
- https://pypi.org/project/whisper-normalizer/ — 0.1.15, 2026-07-26, MIT.
- https://kurianbenoy.github.io/whisper_normalizer/ — BasicTextNormalizer for non-English.
- https://pypi.org/project/dateparser/ — dateparser 1.4.3, 2026-09-03, BSD-3-Clause.
- https://dateparser.readthedocs.io/en/latest/settings.html — PREFER_DATES_FROM, RELATIVE_BASE, TIMEZONE.
- https://github.com/scrapinghub/dateparser/blob/master/dateparser/data/date_translation_data/es.py — Spanish data lacks "pasado mañana", "que viene", "de hoy en ocho".
- https://pypi.org/project/parsedatetime/ — parsedatetime 2.6, 2020-05-31, Apache-2.0.
- https://pypi.org/project/recognizers-text-date-time/ — 1.0.2a2, 2019-11-12, MIT.
- https://github.com/microsoft/Recognizers-Text — last commit 2026-01-23 (.NET CVE fix); Python still alpha.
- https://github.com/facebook/duckling — BSD, Haskell server, `/parse` with locale/text/dims.
- https://github.com/facebook/duckling/blob/main/Duckling/Dimensions/ES.hs — Spanish dims: Distance, Duration, Numeral, Ordinal, Quantity, Temperature, Time, Volume.
- https://hub.docker.com/r/rasa/duckling — `docker run -p 8000:8000 rasa/duckling`.
- https://pypi.org/project/python-dateutil/ — 2.9.0.post0, 2024-03-01, Apache-2.0/BSD.
- https://pypi.org/project/holidays/ — holidays 0.104, 2026-09-07, MIT.
- https://holidays.readthedocs.io/en/latest/ — ES subdivisions incl. MD; `country_holidays("ES", subdiv="MD")`.
- https://pypi.org/project/workalendar/ — 17.0.0, 2023-01-01, MIT.
- https://pypi.org/project/geopy/ — geopy 2.5.0, 2026-07-12, MIT.
- https://pypi.org/project/haversine/ — haversine 2.9.0, 2024-11-28, MIT.
- https://github.com/IDEESpain/Cartociudad — REST endpoints, parameters, response fields, EUPL-1.2.
- https://blog-idee.blogspot.com/2024/08/actualizacion-del-servicio-rest.html — Aug 2024 update: portals return coordinates in `candidates`; new filters.
- https://www.cartociudad.es/geocoder/api/geocoder/candidates?q=Calle%20de%20Alcal%C3%A1%20200%2C%20Madrid&limit=3 — live probe, portal-level result.
- https://data.europa.eu/data/datasets/spaignrest_cartociudad_address — CartoCiudad listed as Spain REST geocoder on data.europa.eu.
- https://operations.osmfoundation.org/policies/nominatim/ — 1 req/s, User-Agent required, caching required, no autocomplete.
- https://github.com/komoot/photon — Photon public API: no hard limit, throttled, run your own for volume.
- https://developers.google.com/maps/billing-and-pricing/pricing — Geocoding: 10,000 free events/month, then $5.00 per 1,000.
- https://developers.google.com/maps/documentation/geocoding/usage-and-billing — 3,000 QPM; v4 25 QPS default.
- https://www.mapbox.com/pricing — Temporary geocoding 100,000 free/month, then $0.75 per 1,000; Permanent $5.00 per 1,000.
- https://developers.openai.com/api/docs/guides/function-calling — `strict: true` rules, forced `tool_choice`.
- https://openai.com/index/introducing-structured-outputs-in-the-api/ — Structured Outputs announcement.
- https://docs.vllm.ai/en/latest/features/structured_outputs/ — backend `auto` (xgrammar/guidance), `response_format` and `structured_outputs` extra_body.
- https://pypi.org/project/outlines/ — outlines 1.3.3, 2026-08-06, Apache-2.0.
- https://github.com/dottxt-ai/outlines — JSON/regex/CFG; transformers, llama.cpp, vLLM, Ollama, OpenAI.
- https://pypi.org/project/lm-format-enforcer/ — 0.11.3, 2025-08-24, MIT.
- https://github.com/noamgat/lm-format-enforcer — integrations: transformers, vLLM, llama.cpp, TensorRT-LLM.
- https://pypi.org/project/xgrammar/ — xgrammar 0.2.7, 2026-09-15, Apache-2.0.
- https://arxiv.org/pdf/2411.15100 — XGrammar paper: up to 3.5x on JSON schema vs prior engines.
- https://pypi.org/project/pydantic/ — pydantic 2.13.5, 2026-08-28, MIT.
- https://pypi.org/project/instructor/ — instructor 1.17.0, 2026-09-09, MIT.
- https://docs.pipecat.ai/guides/learn/function-calling — FunctionSchema, ToolsSchema, `register_function`; no `strict` mention.
- https://pypi.org/project/pipecat-ai/ — pipecat-ai 1.11.0, 2026-09-18, BSD-2-Clause.
- https://soniox.com/docs/stt/concepts/context — `context.terms`, `general`, `text`, `translation_terms`; 8,000-token cap.
- https://soniox.com/docs/stt/models — stt-rt-v5 / stt-async-v5: better alphanumerics, names, codes; robust context.
- https://soniox.com/wiki/context-biasing — how keyword boosting works (shallow fusion; boosted, not mandatory).
- https://arxiv.org/abs/2409.15353 — Phonetic retrieval-based augmentation for named entities; NE error −73.6%.
- https://arxiv.org/abs/2505.17410 — GER for rare words with synthetic data and phonetic context (Interspeech 2025).
- https://arxiv.org/abs/2405.10025 — ClozeGER (ACL 2024): cloze over N-best differences.
- https://arxiv.org/abs/2409.00217 — ProGRes: prompted generative rescoring on N-best, 5-25% WER gain.
- https://arxiv.org/abs/2512.21828 — Contextual biasing for LLM-ASR with hotword retrieval and RL (Dec 2025).
- https://arxiv.org/abs/2604.12398 — Contextual biasing in speech LLMs with common-word cues (Apr 2026).
- https://arxiv.org/abs/2505.19179 — BR-ASR: bias retrieval up to 200k entries.
- https://arxiv.org/pdf/2501.10734 — GEC-RAG: retrieval-augmented generative error correction.
- https://arxiv.org/pdf/2508.07285 — Survey of non-intrusive ASR refinement (2025).
- https://docs.vapi.ai/prompting-guide — read-back and one-field-per-turn guidance for voice agents.
- https://www.twilio.com/en-us/blog/tips-speech-recognition-virtual-agent-voice-calling — alphanumerics are the hardest field; ask for partial ids.
- https://github.com/livekit/agents/pull/6990 — spell the value back once when the caller refuses a confirmation.
- https://pypi.org/project/sentence-transformers/ — 6.1.0, 2026-09-18, Apache-2.0.
- https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 — 0.1B params, 384-dim, 50 languages, Apache-2.0.
- https://pypi.org/project/FlagEmbedding/ — 1.4.2, 2026-08-24.
- https://huggingface.co/BAAI/bge-m3 — 1024-dim, 100+ languages, MIT.
- https://pypi.org/project/model2vec/ — model2vec 0.9.0, 2026-08-12, MIT.
- https://github.com/MinishLab/model2vec — potion-multilingual-128M distilled from bge-m3; up to 500x faster on CPU.
- https://pmc.ncbi.nlm.nih.gov/articles/PMC11352596/ — multilingual symptom entity normalization with adapted BERT (background only).
