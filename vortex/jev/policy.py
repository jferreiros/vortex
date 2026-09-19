from __future__ import annotations

from vortex.contract import Action, EscalateAction, NoAction

RED_FLAG_ESCALATE = 0.85
OUT_OF_SCOPE_VETO_BOOKING = 0.90
OUT_OF_SCOPE_KEEP_REFUSAL = 0.80
BOOKING_KINDS = frozenset({"book", "register", "reschedule", "cancel"})


def decide(
    proposed: Action,
    *,
    red_flag: float | None,
    out_of_scope: float | None,
) -> Action:
    """Rewrite only escalate / out_of_scope. Never touch a slot or a provider."""
    flag = red_flag if red_flag is not None else 0.0
    scope = out_of_scope if out_of_scope is not None else 0.0
    if flag >= RED_FLAG_ESCALATE:
        return EscalateAction(reason="medical_emergency")
    if proposed.kind in BOOKING_KINDS:
        if scope >= OUT_OF_SCOPE_VETO_BOOKING:
            return NoAction(reason="out_of_scope")
        return proposed
    if proposed.kind == "escalate":
        return proposed
    if scope >= OUT_OF_SCOPE_KEEP_REFUSAL:
        return NoAction(reason="out_of_scope")
    return proposed
