"""rules/triage.py: the published red flags and the symptom -> specialty table.

``evals/logic/cases/triage.yaml`` runs the full published table, in English,
Spanish and Catalan. What lives here is what that file doesn't reach: a red
flag paraphrased in a language it isn't tried in yet, the negative case that
proves an everyday symptom never trips one, and the one exception the table
carries by name (heavy periods are never the haemorrhage red flag).
"""

from __future__ import annotations

from vortex.rules.triage import red_flag, route


def test_stroke_red_flag_in_spanish() -> None:
    complaint = (
        "de repente se le ha caido la cara de un lado y tiene el brazo dormido, "
        "no se le entiende al hablar"
    )
    assert red_flag(complaint) == "stroke"


def test_breathless_red_flag_in_spanish() -> None:
    complaint = "no puede respirar en absoluto, le ha dado de repente"
    assert red_flag(complaint) == "breathless"


def test_head_injury_red_flag_in_catalan() -> None:
    complaint = "s'ha donat un cop al cap fa una hora, esta confos i ha vomitat"
    assert red_flag(complaint) == "head_injury"


def test_haemorrhage_red_flag_on_a_wound_not_yet_seen_in_the_corpus() -> None:
    complaint = "he had a fall and the gash on his leg is bleeding heavily, it will not stop"
    assert red_flag(complaint) == "haemorrhage"


def test_heavy_periods_are_never_the_haemorrhage_red_flag() -> None:
    """Problem 6's gynaecology row and problem 10's red flag share the word
    'heavy'; the table's own ``unless`` keeps them apart."""
    complaint = "very heavy, irregular periods for months, soaking through in an hour"
    assert red_flag(complaint) is None
    assert route(complaint) == "gynaecology"


def test_a_mild_everyday_symptom_never_trips_a_red_flag() -> None:
    complaint = "my ankle has ached a little since yesterday, nothing dramatic"
    assert red_flag(complaint) is None
    assert route(complaint) == "orthopaedics"
