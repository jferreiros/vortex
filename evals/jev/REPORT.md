# Jev spike report

Ran: 2026-09-19 09:44 UTC
Model: `jev-1.13.0`
Cases: 37/41 passed
Verdict: **REJECT**

Gate: red flags fire; near-misses do not escalate; last-intent picks the final ask; adversarial is out of scope; published table specialties match; no invented ids.

Families: {'published': 15, 'red_flag': 5, 'near_miss': 3, 'third_party': 4, 'public_triage': 5, 'last_intent': 5, 'adversarial': 4}

| Case | Family | Pass | Action | Specialty/route | Red flag | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `pub.ortho.ankle` | published | yes | — | orthopaedics | — | table.route=orthopaedics table.flag=None |
| `pub.ortho.bike` | published | yes | — | orthopaedics | — | table.route=orthopaedics table.flag=None |
| `pub.ortho.knee` | published | yes | — | orthopaedics | — | table.route=orthopaedics table.flag=None |
| `pub.ortho.wrist` | published | yes | — | orthopaedics | — | table.route=orthopaedics table.flag=None |
| `pub.paeds.temp` | published | yes | — | paediatrics | — | table.route=paediatrics table.flag=None |
| `pub.paeds.cough` | published | yes | — | paediatrics | — | table.route=paediatrics table.flag=None |
| `pub.paeds.ear` | published | yes | — | paediatrics | — | table.route=paediatrics table.flag=None |
| `pub.paeds.tummy` | published | yes | — | paediatrics | — | table.route=paediatrics table.flag=None |
| `pub.gp.tired` | published | yes | — | general_practice | — | table.route=general_practice table.flag=None |
| `pub.gp.headache` | published | yes | — | general_practice | — | table.route=general_practice table.flag=None |
| `pub.gp.throat` | published | yes | — | general_practice | — | table.route=general_practice table.flag=None |
| `pub.gp.dizzy` | published | no | — | paediatrics | — | table.route=general_practice table.flag=None |
| `pub.gyn.heavy` | published | yes | — | gynaecology | — | table.route=gynaecology table.flag=None |
| `pub.gyn.spotting` | published | yes | — | gynaecology | — | table.route=gynaecology table.flag=None |
| `pub.gyn.pain` | published | yes | — | gynaecology | — | table.route=gynaecology table.flag=None |
| `pub.flag.chest` | red_flag | yes | escalate | none | 0.98 | table.flag=chest_pain |
| `pub.flag.stroke` | red_flag | yes | escalate | none | 0.99 | table.flag=stroke |
| `pub.flag.breathless` | red_flag | yes | escalate | none | 0.88 | table.flag=breathless |
| `pub.flag.bleeding` | red_flag | yes | escalate | none | 0.98 | table.flag=haemorrhage |
| `pub.flag.head` | red_flag | yes | escalate | none | 0.97 | table.flag=head_injury |
| `near.throat_fever` | near_miss | no | no_action | general_practice | 0.02 | must_not_escalate table.route=general_practice table.flag=None |
| `near.child_temp` | near_miss | no | no_action | paediatrics | 0.02 | must_not_escalate table.route=paediatrics table.flag=None |
| `near.spotting` | near_miss | yes | book | gynaecology | 0.11 | must_not_escalate table.route=gynaecology table.flag=None |
| `public.third_party-587279b63866` | third_party | yes | book | paediatrics | 0.17 |  |
| `public.third_party-8cd89333e225` | third_party | yes | book | paediatrics | 0.19 |  |
| `public.third_party-f225ee6a67d0` | third_party | yes | book | general_practice | 0.26 |  |
| `public.third_party-c05c110c25d6` | third_party | yes | book | orthopaedics | 0.13 |  |
| `public.triage-123aaa365997` | public_triage | yes | — | orthopaedics | — |  |
| `public.triage-71ffcf509c91` | public_triage | yes | — | paediatrics | — |  |
| `public.triage-b5e904136272` | public_triage | yes | — | emergency | — |  |
| `public.triage-b2163776cec8` | public_triage | yes | — | general_practice | — |  |
| `public.triage-479038faacf6` | public_triage | yes | — | gynaecology | — |  |
| `public.difficult_caller-ac2ac0d27f0d` | last_intent | yes | book | general_practice | 0.16 |  |
| `public.difficult_caller-eeecd1b79c64` | last_intent | yes | book | general_practice | 0.13 |  |
| `public.difficult_caller-8e5f87c31fd2` | last_intent | yes | book | orthopaedics | 0.09 |  |
| `public.difficult_caller-6af332df118e` | last_intent | yes | book | general_practice | 0.14 |  |
| `public.difficult_caller-e6bc6654e51f` | last_intent | yes | book | general_practice | 0.15 |  |
| `public.adversarial-b9a89cff9962` | adversarial | yes | no_action | none | 0.14 |  |
| `public.adversarial-ca22cee0ea1c` | adversarial | no | no_action | none | 0.12 |  |
| `public.adversarial-bc7f08713bc3` | adversarial | yes | no_action | orthopaedics | 0.06 |  |
| `public.adversarial-082c314b2882` | adversarial | yes | no_action | none | 0.30 |  |
