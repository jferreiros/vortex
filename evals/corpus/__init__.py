"""Layer 4 — the organisers' own case roster, and the surface it is drawn from.

``cases/public-cases.json`` is the file the Problems page publishes: 73 cases
with the persona, the caller prompt, the audio bed, the protected fields and
the set of actions each case accepts. It is the only published ground truth in
the challenge, and it is what the other three layers were written without.

- ``catalogue`` loads and indexes it.
- ``normalize`` and ``judge`` replicate the automatic scorer, so a free
  practice call yields the verdict a scored run would give, and the field that lost.
- ``probes`` enumerates the documented surface the private pool is drawn from —
  the private cases are generated from the same templates, so passing the four
  we can see proves little about the four we cannot.
- ``fetch`` refreshes the roster; ``snapshot`` freezes the real clinic once a
  key exists.
"""
