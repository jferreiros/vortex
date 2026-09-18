# Vortex evals — results branch

Every run of `python -m evals` that someone published lands here, in full.
Nothing on this branch is edited by hand.

| Path | What |
| --- | --- |
| `runs/<layer>/<stamp>-<sha>.json` | one run, every case, every transcript |
| `latest/<layer>.json` | the last run of each layer |
| `index.json` | one entry per run: verdict, totals, per-model numbers, routing |

The page at https://jferreiros.github.io/vortex/bench.html reads `index.json`
and `latest/bench.json` from this branch. To add a run:

```bash
make bench            # or make evals, make evals-conversation BRAIN=model ...
make bench-publish    # == uv run python -m evals publish
```
