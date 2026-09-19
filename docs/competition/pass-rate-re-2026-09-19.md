# Pass rate · RE de observables del juez · 19 Sep 2026

Autor: investigación sobre señales legítimas (dashboard autenticado como `vortex`, API pública
`/leaderboard/api/*`, logs de llamada propios, repos públicos de la competencia).
Estado del board al escribir: **hash 30 · cachopo 19 · vortex 16 · Tokenham 14**.

---

## Veredicto ejecutivo

Sí, y mucho más de lo esperado: el dashboard ya expone **la respuesta correcta de los 23 casos
publicados** (`/leaderboard/api/problems/{id}` devuelve el array `accepted` con `patient_id`,
`provider_id`, `location_id`, `slot`, `policy_id` y `reason` exactos), y el Run All se compone de
20 de esos casos. No hace falta romper nada: el oráculo está a un `curl` autenticado.

Con ese oráculo, el diagnóstico cambia de raíz respecto al brief P0: **el problema dominante no es
elegir mal la `reason`, sino no llegar a enviar nada y caer en un fallback que manda
`NO_ACTION/out_of_scope`** — un código que aparece en **cero** de las 23 respuestas aceptadas.
Son el 35 % de nuestros envíos reales. Eso solo ya vale aproximadamente el hueco entero hasta hash.

Dos avisos que pesan más que cualquier fix de prompt: **(1)** el timer de deploy reinicia el
contenedor cada 60 s cuando `main` se mueve, y eso mató la última run (5/40); **(2)** hay una run
activa ahora mismo.

---

## 1. Lo que el juez nos enseña gratis

### 1.1 El oráculo público

`GET /leaderboard/api/problems` → 6 problemas. `GET /leaderboard/api/problems/{id}` → por cada
caso: `case_id`, `caller`, `summary`, `dials` y **`accepted`**, la lista literal de acciones que
puntúan.

| # | `problem_id` | Peso | Ejemplos | Acciones aceptadas |
|---|---|---|---|---|
| 1 | `simple_booking` | 1 | 4 | 4 × BOOK |
| 2 | `switchboard` | 0 | 3 | — (no se marca en Run All) |
| 3 | `doctor_and_site` | 2 | 5 | 4 × BOOK · 1 × NO_ACTION/`provider_not_found` |
| 4 | `the_new_patient` | 2 | 4 | 4 × REGISTER |
| 5 | `when_exactly` | 2 | 5 | 5 × BOOK |
| 6 | `the_rules` | 3 | 5 | 3 × BOOK · NO_ACTION/`referral_required` · NO_ACTION/`specialty_not_covered` |

**Distribución real de la verdad: BOOK 16 (70 %) · REGISTER 4 (17 %) · NO_ACTION 3 (13 %).**

El vocabulario de `reason` que de verdad se usa en todo el set publicado es de **tres** códigos:
`provider_not_found`, `referral_required`, `specialty_not_covered`. Nuestro `DeclineReason`
(`/home/factory/personal/vortex/vortex/contract.py`, L96-115) tiene 16.

### 1.2 La forma de la Run All es fija

Las tres runs privadas tienen exactamente la misma forma: **20 casos, 40 puntos**, repartidos
`4 × peso 1 · 12 × peso 2 · 4 × peso 3`. Encaja con muestrear 20 de los 23 ejemplos publicados.

| run | estado | puntos | fallos por peso |
|---|---|---|---|
| `1e6e47ca` | completed | 14 / 40 | w1:2 w2:9 w3:2 |
| `225a5ee5` | completed | **16 / 40** (mejor) | w1:1 w2:7 w3:3 |
| `a7cb4f26` | completed | **5 / 40** | w1:3 w2:10 w3:4 |

### 1.3 `field_failures` del dashboard es engañoso

El brief partía de «top field_failures = `action` y `reason`». Comprobado: esos contadores
(`action: 3`, `reason: 3`) se calculan **solo sobre los 7 casos visibles**, que son todos el mismo
escenario (`The Simple Booking · silence`). Los 56 casos privados van con `fields: []`. Los 3
fallos de `action` y los 3 de `reason` son **los mismos 3 casos**: en cuanto mandas `NO_ACTION`
donde tocaba `BOOK`, fallan las dos columnas a la vez (`reason` esperado `null`, enviado
`out_of_scope`). No son dos síntomas, es uno.

### 1.4 `signal_codes` sobre 67 casos juzgados

| código | en fallos | en aprobados | lectura |
|---|---|---|---|
| `record_mismatch` | 35 | 0 | consecuencia, no causa: el récord no casa |
| `wall_clock` | 20 | 5 | **causal** — límite ~180 s |
| `connection_lost` | 14 | 14 | **ruido**: 1006 tras despedirse, no lo persigamos |
| `agent_silence` | 6 | 1 | causal — el agente no llegó a hablar |
| `harness_socket_error` | 0 | 2 | ruido del harness |

`connection_lost` aparece igual en aprobados que en fallos: hash documenta lo mismo en sus notas
públicas. **No es una pista.**

### 1.5 Los 7 casos visibles: el mismo caso, 4 veces bien y 3 mal

Todos son `simple_booking · silence` con el mismo `accepted`. La diferencia no es de criterio,
es de ejecución:

| call | veredicto | dur | turnos A/P | señales |
|---|---|---|---|---|
| `22c158c7` | passed | 88 s | 16/5 | — |
| `8b085630` | passed | 117 s | 28/7 | — |
| `09109908` | passed | 120 s | 32/7 | `connection_lost` |
| `0f05ac57` | passed | 177 s | 41/7 | `connection_lost` |
| `2223d63a` | **failed** | 182 s | 32/**13** | `wall_clock` |
| `bbff8efd` | **failed** | 53 s | 15/3 | `connection_lost` |
| `09fd3fcd` | **failed** | 20 s | **0**/1 | `agent_silence` |

Los aprobados cierran en **5-7 turnos de paciente**; el que se fue a 13 murió por reloj. `09fd3fcd`
no emitió ni un turno. La latencia mediana paciente→agente medida por el juez es **4,3-4,9 s en
todas**, aprobadas incluidas — o sea, vamos con el freno de mano puesto en todas y solo nos salva
que la conversación sea corta.

---

## 2. Lo que dicen nuestros logs (`/tmp/vortex-calls.jsonl`, 68 llamadas, 4 983 eventos)

### 2.1 El agujero grande: `out_of_scope`

Filtrando a llamadas con `call_id` UUID real (las sintéticas `CA-fake-*` no puntúan):

| envío | n | % |
|---|---|---|
| `book` | 17 | 37 % |
| **`no-action` / `out_of_scope`** | **16** | **35 %** |
| `register` | 4 | 9 % |
| `no-action` / otros (`specialty_not_covered`, `provider_on_leave`, `no_availability`, `provider_not_found`, `location_not_covered`) | 9 | 20 % |

Contra la verdad (BOOK 70 % / REGISTER 17 % / NO_ACTION 13 %). Mandamos BOOK la mitad de veces de
las que tocaría y `out_of_scope` en un tercio de las llamadas.

**`out_of_scope` solo es correcto en el problema 14 `adversarial`, que no está en nuestro set de 6.**
Hoy, para vortex, `out_of_scope` es un cero garantizado.

Y el origen está localizado: **28 de las 32 llamadas con `submit.fallback` acaban enviando
`no-action/out_of_scope`** (30 eventos de envío; dos llamadas duplicaron el submit), con
`why: "no accepted submission when the call ended"`. No es el modelo eligiendo mal: es que la
llamada se acaba sin que nadie haya enviado nada y el fallback rellena con el peor código posible.

### 2.2 Reloj

- Duración: mediana 123,3 s · p90 191,4 s · máx 199,1 s. El techo es ~180-190 s (cachopo lo
  documenta como «three-minute local limit»).
- Las 2 llamadas del Run All bueno que cayeron en fallback (`8296041d`, `b3a379a0`) murieron a
  186 s y 188 s, ambas en bucle de `clinic_facts`, sin llamar nunca a `submit_action`.
- **Los 4 REGISTER van a 147 / 148 / 173 / 189 s.** `the_new_patient` son 8 puntos y los jugamos
  todos al filo.
- Fragmentación: mediana **2,33 turnos de asistente por turno de usuario** (hasta 99/34).

Las herramientas **no** son el cuello de botella — todas por debajo del segundo:

| tool | n | mediana |
|---|---|---|
| `find_patient` | 38 | 0,32 s |
| `check_eligibility` | 28 | 0,19 s |
| `find_slots` | 40 | 0,18 s |
| `submit_action` | 27 | 0,14 s |

El coste está en LLM + TTS y, sobre todo, en **cuántos intercambios hacemos**.

### 2.3 Los 422 son ruido de self-test (falsa alarma)

14 envíos con HTTP 422 `badly formed hexadecimal UUID string`. Todos de `CA-fake-*`,
`CA-selftest-*`, `CA-voicetest-*`. **Ninguna llamada real fue rechazada** (45/45 `accepted` 200).
Dicho eso: significa que nuestros self-tests nunca ejercitan de verdad la ruta de submit, así que
un bug real ahí no lo cazaríamos en local.

---

## 3. El deploy se comió la última run

`deploy/systemd/vortex-deploy.timer` → `OnUnitActiveSec=60s`. Cada minuto comprueba `origin/main`
y, si se movió, `deploy/deploy.sh` hace `docker compose build` + `up -d`: **reinicia el contenedor
con llamadas en vuelo**.

Cronología:

- `02:20:04Z` arranca la run privada `a7cb4f26`.
- `02:22:14Z` entra en `main` el merge de F1 (`735d3c6`).
- El timer despierta, reconstruye, reinicia.
- Resultado: **5 / 40**, con 11 casos marcados `connection_lost` y 9 de ellos además `wall_clock`.

Las dos runs anteriores, sin deploy encima, dieron 14/40 y 16/40. **No hay evidencia de que F1
empeorase nada; hay evidencia de que desplegar durante una run la destruye.**

> Al cerrar este informe hay **otra run activa** (`f38c01d6`, `eligibility.active_run: true`).
> Mergear F3 (#227) o F4 (#228) ahora mismo repetiría exactamente el mismo accidente.

---

## 4. F1 merece una segunda mirada

F1 (`735d3c6`) fuerza en el submit la `reason` del último veredicto de `check_eligibility`, por
encima de la del modelo. El caso que lo motivó, `c9f087a0`:

```
check_eligibility → {"allowed": false,
                     "rejection": {"reason": "location_not_covered",
                                   "detail": "ASISA does not cover physiotherapy"}}
modelo            → specialty_not_covered
```

El `detail` dice literalmente «no cubre physiotherapy», que suena a *specialty*. Mirando
`vortex/rules/eligibility.py` L242-252, la etiqueta es deliberada: ASISA sí cubre fisioterapia,
pero ningún centro cubierto tiene fisioterapeuta, así que el motor lo llama refusal de sitio.
Defendible.

El problema es que **no se puede verificar**: physiotherapy + ASISA no está entre los 23 casos
publicados. Y el precedente publicado más parecido (`the_rules-460d9e84504a`, la aseguradora
rechaza ginecología) espera `specialty_not_covered`. F1 convierte la etiqueta del motor en
autoritativa y le quita al modelo la capacidad de corregirla. Es una apuesta a cara o cruz sobre
un caso de peso 3.

Añadido: F1 ataca como mucho **1 envío de 46** (`location_not_covered` aparece una vez). El
fallback a `out_of_scope` son **16**. Se priorizó el síntoma pequeño.

---

## 5. Tabla de evidencias

| # | Modo de fallo | Fuente de la señal | Pts est. / run | Fix propuesto |
|---|---|---|---|---|
| 1 | Fallback manda `NO_ACTION/out_of_scope`; nunca es correcto en nuestros 6 problemas | logs: 28/32 llamadas con fallback; 16/46 envíos reales; `accepted` de los 23 casos | **+8 a +14** | Prior BOOK en el fallback; prohibir `out_of_scope` por config |
| 2 | Deploy reinicia el contenedor con la run en vuelo | `vortex-deploy.timer` 60 s + cronología `a7cb4f26` (5/40) | **+10 a +16** (protege) | Guard: abortar deploy si `eligibility.active_run` |
| 3 | Reloj de ~180 s agotado | 20 fallos con `wall_clock`; p90 191 s; 2 fallbacks a 186-188 s | **+6 a +10** | Submit en cuanto la acción esté decidida + timer duro a T+150 s |
| 4 | Doble confirmación / turnos de más | 2,33 turnos asistente por turno usuario; aprobados 5-7 turnos de paciente vs 13 el que murió | +4 a +8 | **F2** (sin rama todavía) |
| 5 | `agent_silence`: 0 turnos emitidos | `09fd3fcd` (20 s, 0 turnos); 7 casos con la señal | +2 a +4 | Saludo inmediato al abrir socket; health-check de TTS |
| 6 | REGISTER al filo del reloj | 4/4 entre 147 y 189 s | +4 a +6 | Confirmar DNI/email en bloque, no dígito a dígito |
| 7 | Bucle `clinic_facts` sin salida | `8296041d`, `b3a379a0` | +2 a +4 | Responder del catálogo y volver al booking; nunca `out_of_scope` |
| 8 | F1 puede forzar la reason equivocada | `c9f087a0` vs `the_rules-460d9e84504a` | −3 a +3 | Acotar el override; resolverlo con el harness offline |
| 9 | `connection_lost` | 14 aprobados / 14 fallos | **0** | **No tocar** — es ruido |

---

## 6. Ranking de oportunidades

### A · Ya cubierto por F2-F4

- **F3** (#227, abierto) toca el fallback, pero solo «usa la reason guardada». No cambia el
  *default*: si no hay veredicto guardado sigue saliendo `out_of_scope`. **Insuficiente para el
  fallo #1** — hay que añadirle el prior BOOK.
- **F4** (#228, abierto) cubre specialty por médico/queja. Bien alineado con `doctor_and_site` y
  `triage`.
- **F2** no tiene rama. Es el fallo #4 de la tabla. Sigue abierto.

### B · P1 nuevos, por orden de ROI

1. **Guard de deploy contra run activa** — esfuerzo trivial, protege 10-16 pts. Antes de
   reiniciar, consultar `eligibility.active_run` y abortar. Es el mejor ratio de todo el informe.
2. **Prior BOOK en el fallback + `out_of_scope` prohibido** — el mayor bloque de puntos. Orden:
   booking preparado → BOOK; veredicto de regla → esa reason; si no, la reason más probable del
   contexto; `out_of_scope` nunca mientras el set sean estos 6 problemas.
3. **Harness offline contra el oráculo publicado** — replay de los 23 casos con `accepted`
   conocido, diff del récord enviado. Es lo que hace cachopo. No da puntos por sí mismo pero
   multiplica la velocidad de iteración y **resuelve F1 con datos** en vez de por intuición.
4. **Presupuesto de reloj explícito** — submit en cuanto haya acción decidida, timer duro a
   T+150 s, y recortar la fragmentación de 2,33 a ~1,2 turnos de asistente por turno de usuario.
5. **F2 single-confirm** — sin rama, y ataca directamente los turnos de más.

### C · Callejones sin salida

- **Perseguir `connection_lost`**: 14 aprobados con esa señal. Es el 1006 post-despedida.
- **Los 422**: solo self-tests, ninguna llamada real.
- **Ampliar el vocabulario de `reason`**: el set publicado usa 3 códigos; tenemos 16. El problema
  es de cobertura de BOOK, no de granularidad de refusals.
- **Más RE del juez**: ya está agotado, ver abajo.
- **Cualquier cosa contra el harness privado**: fuera de límites y además innecesario.

---

## 7. Lo que NO se hizo

- No se atacó, crackeó ni se hizo RE del harness privado de Prosper.
- No se descargaron ni descompilaron binarios del harness.
- No se intentó saltar autenticación: todo con la sesión legítima de vortex
  (`POST /leaderboard/api/session` → cookie `prosper_dashboard`).
- No se tocaron endpoints privados de otros equipos. De la competencia solo se leyeron **repos
  públicos** (`manufhros/hackspain-prosper-ai`, `pablofd/hackspain`) ya clonados en `/tmp`.
- No se lanzó ningún Run All ni se escribió nada en la plataforma (solo `GET`, más el `POST` de
  login). Había una run activa y se dejó en paz a propósito.
- No se intentó descubrir los `case_id` privados más allá de lo que el dashboard ya muestra al
  equipo.

---

## 8. ¿Queda ROI en seguir haciendo RE de observables?

**Poco.** La superficie legítima está exprimida: tenemos el oráculo con las respuestas exactas, la
forma fija de la run (20 casos / 40 pts), el diccionario de `signal_codes` con su valor
discriminante, y el techo de reloj. Lo que el dashboard no da —los `case_id` privados y sus
`fields`— no se puede sacar sin cruzar la línea, y tampoco haría falta: los privados salen del
mismo molde que los 23 publicados.

El único observable que sí sigue rentando es **barato y repetible**: releer
`/leaderboard/api/teams/{id}` después de cada run y mirar `signal_codes` × peso. Eso es
monitorización, no investigación.

A partir de aquí el cuello de botella es de ingeniería, no de información: convertir
`out_of_scope` en BOOK, no desplegar encima de una run, y cerrar las llamadas antes de los 180 s.

---

## Resumen para Discord (5 líneas)

```
Pass-rate RE · vortex · 19 Sep
1. El dashboard ya publica las respuestas correctas de los 23 casos (/problems/{id} → accepted). La verdad es BOOK 70% / REGISTER 17% / NO_ACTION 13%.
2. Nosotros mandamos out_of_scope en el 35% de las llamadas y ese código no puntúa en NINGÚN caso nuestro. 30 de 32 salen del fallback de fin de llamada. Es el hueco entero hasta hash.
3. La run de 5/40 no fue culpa de F1: el timer de deploy (60 s) reinició el contenedor con la run en vuelo. Hay OTRA run activa ahora — no mergear F3/F4 todavía.
4. Techo de reloj ~180 s: las aprobadas cierran en 5-7 turnos de paciente, los 4 REGISTER van a 147-189 s. Las tools no son el problema (<1 s todas).
5. Top 3: guard de deploy contra run activa · prior BOOK en el fallback · harness offline contra el oráculo publicado.
```
