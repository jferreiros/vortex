# Opus implementation brief — P0 compete fixes

Triggered at **04:25 CEST 19 Sep 2026**. Repo: `/home/factory/personal/vortex`. Base: `main`.

Read first: `docs/competition/gap-hash-cachopo-2026-09-19.md`

## Rules

- One PR per fix ID (F1…F4). Branch `fix/compete-F{n}-{slug}`.
- Use Opus. Small diffs. Tests for the failure mode.
- Do **not** invent credentials. Do not touch Discord tokens.
- After each PR: `gh pr create` against `main`, body links the doc section.
- Evidence from logs: `/tmp/vortex-calls.jsonl` and `/tmp/vortex-recent-calls.json` if present.

## F1 — reason override (HIGHEST)

**Bug:** call `c9f087a0` — `check_eligibility` returned `location_not_covered` (ASISA + physiotherapy) but model submitted `specialty_not_covered`.

**Fix:** When submitting `no-action` / `escalate`, if the session has a last eligibility or availability `blocked` reason, **force that reason** regardless of model args. Log the override.

Likely files: `vortex/line/session.py`, submit path in `vortex/tools.py` / line submit module, store last verdict on `ToolContext` / `CallSession`.

Test: unit that mocks last verdict `location_not_covered` and model says `specialty_not_covered` → POST body has `location_not_covered`.

## F2 — single confirmation

**Bug:** Hash lose pts when agent asks to confirm twice after «yes, book it».

**Fix:** Prompt + guard: if last assistant turn was a booking confirmation question and user affirms, call `submit_action` with prepared booking **without** asking again.

Files: `vortex/conversation/prompt.py`, possibly turn policy in `vortex/conversation/turns.py`.

## F3 — hangup fallback reason

**Bug:** `bbff8efd` ended mid-identity → `submit.fallback` `out_of_scope`.

**Fix:** In `CallSession` fallback (~L350 in `session.py`): if a `RuleVerdict` / blocked reason is stored, use it; if no patient identified yet, prefer not inventing `out_of_scope` unless problem-14 shaped — document choice in PR. At minimum: never overwrite a better reason.

## F4 — specialty from doctor / complaint

**Bug:** Hash notes — wrist + Dr Iglesia searched as GP.

**Fix:** `triage` + `find_provider`: if provider name resolves, use their specialty; published complaints map to specialty (existing catalogue). Prompt: never default `general_practice` when a named doctor or mapped complaint exists.

---

## Done criteria per PR

- [ ] Branch pushed
- [ ] Test fails on main scenario without fix, passes with fix
- [ ] `gh pr create` with title `fix(compete): F{n} …`
- [ ] No secrets in diff
