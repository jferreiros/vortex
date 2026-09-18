from evals.common.discord_msg import overall_verdict, pr_comment, webhook_body


def _summary():
    return {
        "logic": {
            "verdict": "FAIL",
            "totals": {
                "pass": 23,
                "fail": 82,
                "error": 0,
                "unverified": 0,
                "skipped": 0,
                "hollow": 23,
            },
            "broke": ["diary.date.day_after_tomorrow"],
            "fixed": [],
            "git": {"sha": "deadbee", "branch": "feat/x"},
        },
        "conversation": {
            "verdict": "PASS",
            "totals": {
                "pass": 2,
                "fail": 0,
                "error": 0,
                "unverified": 0,
                "skipped": 0,
                "hollow": 0,
            },
            "broke": [],
            "fixed": ["p1.simple"],
            "git": {"sha": "deadbee", "branch": "feat/x"},
        },
    }


def test_overall_fail_wins():
    assert overall_verdict(_summary()) == "FAIL"


def test_embed_names_layers_and_sha():
    body = webhook_body(_summary(), wall="https://example.test/wall")
    assert body["username"] == "Vortex evals"
    embed = body["embeds"][0]
    assert embed["title"] == "Evals FAIL"
    assert "logic" in embed["description"]
    assert "conversation" in embed["description"]
    assert "deadbee" in embed["footer"]["text"]
    assert embed["url"] == "https://example.test/wall"


def test_pr_comment_has_marker_and_table():
    md = pr_comment(_summary())
    assert md.startswith("<!-- vortex-evals -->")
    assert "| logic | **FAIL** |" in md
    assert "gate" in md
