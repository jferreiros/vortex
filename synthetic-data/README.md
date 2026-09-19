# synthetic-data

Isolated pack of patients, diaries and CallLog-shaped JSONL built from the
Problems-page public cases (and, optionally, the live clinic API). Same payload
shape as `vortex/clinic/fixtures.py`, different folder — do not mix the two.

Regenerate:

    make evals-hydrate          # from public-cases.json, no key
    make evals-hydrate LIVE=1   # enrich charts and diaries from the API
    uv run python -m evals.corpus.clinic_day   # just the 19 Sep clinic day

`FakeClinicClient()` still reads the small invented fixtures. To read this pack:

    FakeClinicClient(data_dir=Path("synthetic-data"))

`logs/clinic_day.jsonl` is a 19 Sep 2026 clinic day (not a published case):
more volume than the previous mock, 15-20% unresolved by the agent, at most
10% of those escalated (with `medical_emergency`), the rest refused with a
typed `reason`, and three REGISTER calls for new patients.

Never written here: the full availability calendar (`evals/corpus/world/`),
the live call log (`logs/calls.jsonl`), or the fixtures the unit tests own.
