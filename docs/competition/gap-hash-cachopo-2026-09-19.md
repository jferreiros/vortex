# Competencia → fixes Vortex · 19 Sep 04:00 CEST

Board ahora: **hash 30 · cachopo 19 · vortex 16**. Gap a hash = **14 pts**.

Repos: [hash](https://github.com/manufhros/hackspain-prosper-ai) · [cachopo](https://github.com/pablofd/hackspain) · logs `calls.jsonl` Run All ~01:21–01:26 UTC.

---

## Quiénes son

| Equipo | Pts | Repo público | Integrantes |
|---|---|---|---|
| **hash** | 30 | `manufhros/hackspain-prosper-ai` | Manuel Hidalgo Ros, Guillermo Vargas Hidalgo, Lucía Muñoz Martínez |
| **cachopo** | 19 | `pablofd/hackspain` | Pablo Ferrero (+ VynFerrius) |
| **vortex** | 16 | `jferreiros/vortex` | nosotros |

Hash publica dashboard + **run notes** (el agente vive en clon privado de Lucía). Cachopo publica el agente completo (Azure Realtime + Foundry).

---

## Qué hace hash (30 pts) que nosotros no

Sus run notes (15–16/20 passed → ~30 pts) listan fallos que **también vemos en nuestro log**:

1. **Razón NO_ACTION exacta** — vocabulario cerrado. `location_not_covered` ≠ `specialty_not_covered`. En nuestro `c9f087a0` el tool devolvió `location_not_covered` (ASISA + physio) y el modelo mandó `specialty_not_covered` → **fail seguro**.
2. **No inventar GP por defecto** — muñeca + «Dr. Iglesia» = ortopedia. Hash pierden pts cuando buscan `general_practice`.
3. **Una sola confirmación** — tras «yes, book it» → `submit_book` ya. Doble confirm = wall-clock / sin submission.
4. **Silencios (`...`) ≠ fin de llamada** — no `NO_ACTION` hasta colgado o rechazo explícito.
5. **Filtrar slots en código** por día/tramo antes de dárselos al LLM; si vacío, «lo más cercano es X».
6. **REGISTER**: no inventar `second_surname`; validar letra DNI antes de POST.
7. **Médico inexistente** → avisar; si no aceptan otro → `provider_not_found`.
8. **No acumular** NO_ACTION + BOOK en el mismo record.

---

## Qué hace cachopo (19 pts) que podemos copiar

Repo maduro, TypeScript, Azure OpenAI Realtime:

- **Estado aislado por paciente** + invalidación al corregir.
- **Propuesta → confirmación → POST** separados (nunca submit temprano).
- **Routing de quejas** desde catálogo publicado (no adivinar).
- **Reason codes** cableados al tool result, no al prose del modelo.
- **Regressiones offline** por problema (`the_rules`, interruptions, etc.).
- Interruption: clear de cola propia (Prosper no implementa Twilio `clear`).

---

## Nuestro Run All (~01:21 UTC) — lectura del JSON

~20 llamadas concurrentes reales (UUIDs Prosper). Patrones:

| Señal | Ejemplo | Efecto pts |
|---|---|---|
| BOOK/REGISTER aceptados | `0f05ac57`, varios REGISTER, ortopedia | suman (peso del problem) |
| Reason mal mapeada | `c9f087a0`: tool=`location_not_covered`, submit=`specialty_not_covered` | **0** en caso rules/physio |
| Fallback `out_of_scope` mid-ID | `bbff8efd`: cortó pidiendo DOB → fallback | **0** (casi siempre) |
| Pricing loop → `out_of_scope` | `89018a4c` (Sanitas cost) | puede fallar `the_questions` |
| `llm.timeout` post-submit | varios | hangup OK si ya hay submit; riesgo si no |
| Duplicados turn.user/assistant | casi todas | ruido / latencia / barge-in flojo |

16 pts ≈ pocos casos low/mid weight verdes. Hash saca ~doble con la misma forma de Run All pero razón + specialty + confirm correctas.

---

## Backlog de PRs (prioridad → pts)

### P0 — ship antes del CP1 (10:00)

| ID | Fix | Archivos | Por qué |
|---|---|---|---|
| **F1** | `submit_action` **debe usar la `reason` del último `check_eligibility` / `find_slots.blocked`**, no la del LLM. Si el modelo manda otra, override + log. | `vortex/line/session.py` o wrapper de `submit_action`; `vortex/rules/tools.py` | c9f087a0 = pts tirados |
| **F2** | Tras confirmación afirmativa («yes / book it / dale»), **submit inmediato** sin segunda pregunta. | `vortex/conversation/prompt.py` + guard en turns | hash wall-clock fails |
| **F3** | Fallback de fin de llamada: **nunca** `out_of_scope` si hay `RuleVerdict` / blocked reciente; usar esa reason. Si mid-identity → no submit prematuro o `patient_not_found` solo si aplica. | `vortex/line/session.py` (~L350) | bbff8efd |
| **F4** | `triage` / specialty: si hay **nombre de médico** o queja publicada (muñeca, hay fever→allergology), **no default GP**. | `vortex/rules/tools.py` triage + prompt | gap vs hash |

### P1 — siguiente Run All

| ID | Fix | Notas |
|---|---|---|
| **F5** | Filtrar slots por `date_from/to` + `part_of_day` en `find_slots` antes de devolver al modelo; mensaje «no hay ese día; más cercano…». | Ya hay algo en diary; endurecer |
| **F6** | REGISTER: rechazar apellido inventado; `validate_national_id` obligatorio pre-submit. | identity/tools |
| **F7** | Provider no en catálogo → decirlo; `provider_not_found` si no aceptan alternativa. | find_provider |
| **F8** | Una sola acción terminal: bloquear NO_ACTION seguido de BOOK en el mismo call. | session submit guard |
| **F9** | `the_questions`: no bucles de precio; responder desde catálogo o «lo confirma el mostrador» + seguir booking sin `out_of_scope`. | prompt + clinic_facts |
| **F10** | Deduplicar turn events / filler «Un momento» spam (latencia + timeouts). | pipecat_voice / observers |

### P2 — jurado / observabilidad

| ID | Fix |
|---|---|
| **F11** | Panel tipo hash: pegar log Run All → findings automáticos (reason mismatch, double confirm, no submit). |
| **F12** | Regressions estilo cachopo por problem weight ≥3. |

---

## Cómo implementar (para subagentes Opus 4:25)

Cada PR = **un fix F1…Fn**, branch `fix/compete-F{n}-{slug}`, tests + `make verify` / pytest del módulo tocado. No mezclar P0 con P2.

Orden de merge sugerido: **F1 → F3 → F2 → F4 → F5 → F8 → F6 → F7 → F9**.

Referencias en el tree:

- Hash notes: clonar o mirar `web/data/run-notes.json` en su repo
- Cachopo: `AGENTS.md` tabla de fallos + `src/receptionist.ts`
- Nuestro log: docker volume `vortex-line_line-logs` → `calls.jsonl` (dump `/tmp/vortex-recent-calls.json`)

---

## Meta numérica

- Ahora: **16**
- Tras P0 (F1–F4) bien: **+8–14** razonable (reasons + confirms + no fallback basura)
- Empate hash (~30): hace falta P0+P1 y un Run All limpio antes del freeze 05:00 dom.
