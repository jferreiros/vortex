# synthetic-data

Isolated pack of patients, diaries and CallLog-shaped JSONL built from the
Problems-page public cases (and, optionally, the live clinic API). Same payload
shape as `vortex/clinic/fixtures.py`, different folder — do not mix the two.

Regenerate:

    make evals-hydrate          # from public-cases.json, no key
    make evals-hydrate LIVE=1   # enrich charts and diaries from the API

`FakeClinicClient()` still reads the small invented fixtures. To read this pack:

    FakeClinicClient(data_dir=Path("synthetic-data"))

Never written here: the full availability calendar (`evals/corpus/world/`),
the live call log (`logs/calls.jsonl`), or the fixtures the unit tests own.
