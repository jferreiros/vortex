# Discord capture — vortex-hackspain / #evals

Invite used: <https://discord.gg/REDACTED>

Resolved 19 Sep 2026 via Discord's public invite API
(`GET /api/v10/invites/REDACTED?with_counts=true`):

| Field | Value |
| --- | --- |
| Guild | `vortex-hackspain` (`1550611466367799296`) |
| Channel the invite lands on | `#evals` (`1550611553555062974`) |
| Inviter | `jferreiros` |
| Members | 5 (2 online at capture) |
| Invite expires | 2026-10-18 |

Channel message history is not public. The team has no Discord bot (see
`.claude/skills/notify-discord/SKILL.md`); a webhook can post to `#github`
but cannot read `#evals`. The requirements below are the notes Cristina
pasted from Marta UC3M (same morning, 19 Sep 2026).

## Marta UC3M — 19/9/2026

- 11:17 — entre un 15-20% deberían no ser resueltas por el agente (un 10% o
  menos de ellas porque se escalaron a un médico, otras porque se rechazaron.
  las que se rechazaron tienen que tener registrado el motivo del rechazo; las
  que se escalaron, porque se escaló)
- 11:18 — total de llamadas de hoy que sean más
- 11:18 — un par o tres de llamadas nuevas que registren nuevos pacientes

The clinic-day pack (`logs/clinic_day.jsonl`) is built against that mix.
