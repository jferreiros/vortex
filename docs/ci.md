# CI

One workflow, `.github/workflows/ci.yml`. It runs on every pull request and on
every push to `main`. Its job is to answer one question fast: can this merge?

## What runs

| Job | Command | Blocks the merge? |
| --- | --- | --- |
| `test` | `make install` then `make test` | yes |
| `lint` | `make lint` | yes |
| `format` | `make fmt` then `git diff --exit-code` | yes |
| `coverage` | `pytest --cov=vortex`, then a comment on the PR | no, reports only |
| `quality (advisory)` | ruff with stricter rule sets, inline annotations | no, `continue-on-error` |
| `evals (not wired yet)` | placeholder, always skipped | no |
| `gate` | green only if `test`, `lint` and `format` are green | this is the required check |

The five real jobs run in parallel. `gate` is the single status check that
`main` requires, so renaming a job never silently un-protects the branch.

Dependencies come from `uv.lock` with `UV_LOCKED=1`: if `pyproject.toml`
changed and the lock did not, `make install` fails with a clear message. Fix
it locally with `uv lock` and commit `uv.lock`. The uv cache is keyed on
`uv.lock`, so a run with an unchanged lock skips the download.

A new push to the same branch cancels the run still going.

## How long it takes

Measured on `main`, run 35387012908 (first run, cold cache) and the run of
the commit that added this section (warm cache):

| Job | Cold cache | Warm cache |
| --- | --- | --- |
| whole workflow, wall clock | 34 s | 56 s (includes 40 s queued for a runner) |
| `test` | 19 s | 14 s |
| `coverage` | 30 s | 32 s |
| `lint` | 8 s | 10 s |
| `format` | 10 s | 13 s |
| `gate` | 4 s | 4 s |

Locally the whole thing is a few seconds. Most CI time is waiting for a runner,
runner start and checkout; the uv cache keyed on `uv.lock` only shaves the
dependency download, which is small for this lock.

## Coverage

`coverage` runs the suite under `pytest-cov` (pulled in with `uv run --with`,
so `pyproject.toml` stays untouched) with the settings in `.coveragerc`, then
`py-cov-action/python-coverage-comment-action` posts one comment on the PR
with total coverage and the coverage of the changed lines. On a push to `main`
it stores the badge and the HTML report on the
`python-coverage-comment-action-data` branch. That branch is generated; do not
edit it.

There is no threshold on purpose. The repo is mostly stubs and a number now
would only block. Read the comment, do not fight it. The same table also
appears in the job's summary page.

## Reproduce a CI failure locally

Each job is one or two Makefile targets. Run the same thing:

```bash
uv sync --all-groups          # or: make install
make test                     # job `test`
make lint                     # job `lint`
make fmt && git diff          # job `format`: whatever the diff shows, commit it
```

If `make install` fails in CI with "lockfile needs to be updated":

```bash
uv lock && git add uv.lock && git commit -m "chore: refresh uv.lock"
```

Coverage and the advisory ruff pass, if you want them locally:

```bash
uv run --with pytest-cov pytest -q --cov=vortex --cov-report=term-missing:skip-covered
uv run ruff check . --extend-select SIM,C4,PIE,PTH,N,RUF,PL --ignore PLC0415,PLR2004 --statistics
```

Python version: CI uses the one in `.python-version`, same as `uv sync` does
for you. If it passes for you and fails in CI, check `uv run python --version`
first.

Re-run without a new commit: `gh run rerun <run-id>` or the "Re-run jobs"
button. `workflow_dispatch` is enabled, so `gh workflow run CI` works too.

## Branch protection

`main` requires the `gate` check and the branch to be up to date with `main`.
No force pushes, no deletion, no required reviews (five people, one weekend).

It is set by `.github/scripts/protect-main.sh`. It needs the repo owner's
personal `gh` login (`jferreiros`) and is run once:

```bash
gh auth status                       # must say jferreiros
bash .github/scripts/protect-main.sh
gh api repos/jferreiros/vortex/branches/main/protection --jq '.required_status_checks.contexts'
# -> ["gate"]
```

Until that script has been run, a red CI does not stop a merge. Check the
status with the last command above.

## Escape hatch: merging with CI red at 4 a.m.

A CI without a valve gets switched off entirely. This is the valve:

1. Say on the call why it must go in red, and write the same sentence in the
   PR description (the template has a line for it).
2. The repo owner merges past the check. `enforce_admins` is off, so:

   ```bash
   gh pr merge <number> --squash --admin
   ```

   In the web UI the same thing is the "Merge without waiting for
   requirements to be met" checkbox that admins see.
3. Open a follow-up issue or PR titled `fix: CI after #<number>` before you
   go to sleep, so the next person does not inherit a red `main`.

Do not use `[skip ci]` in a commit message on a PR: the workflow does not run
at all, the required check never reports, and the PR cannot be merged even
with `--admin` until someone re-triggers it. Do not disable the workflow or
delete the protection to get one PR through. `--admin` is enough and leaves a
trace in the PR timeline.

If CI itself is broken (an action outage, a runner problem) rather than the
code: `--admin` too, and note it in the PR.

## The evals slot

Another lane is building an evaluation system in `evals/`. The workflow has a
job named `evals (not wired yet)`. It is skipped until the repository variable
`CI_EVALS_ENABLED` is `true`. When `evals/` lands:

1. Put its Makefile target in the job, then enable it once:
   `gh variable set CI_EVALS_ENABLED --body true`.
2. Decide on the call whether it joins `gate`. Evals talk to the platform,
   take minutes and depend on `PLATFORM_API_KEY`, so the default answer is no:
   let it report like `coverage` does, and keep `gate` to what runs offline in
   seconds.
3. If it needs the key, add it as a repository secret and never as a file.

## Code Climate: what we found, and what we use instead

Code Climate Quality no longer exists as a product you can sign up for under
that name. On 11 November 2024 it was spun out into a new company, Qlty
Software, and `codeclimate.com/pricing` now redirects (HTTP 301) to
`qlty.sh/pricing`. Qlty Cloud has a free tier: unlimited public and private
repos, unlimited contributors, 1,000 analysis minutes a month, coverage,
maintainability and duplication, and a GitHub Action (`qltysh/qlty-action`)
with OIDC so no long-lived token is needed. The catch is the same as before:
someone has to log in with GitHub OAuth, install the Qlty GitHub App on
`jferreiros/vortex` and, for coverage, either enable OIDC or copy a
`QLTY_COVERAGE_TOKEN` into the repo secrets. None of that can be done by an
agent, and a half-wired integration would show as a permanently failing check.

So this repo does not depend on Qlty. What covers the same ground without any
new account:

- Coverage on the PR: the `coverage` job and its comment, above.
- Maintainability signals: the `quality (advisory)` job runs ruff with the
  rule sets Code Climate used to flag (`SIM` simplification, `C4`
  comprehensions, `PIE` misc, `PTH` pathlib, `N` naming, `RUF`, `PL`
  pylint-style, minus lazy imports and magic numbers, which are normal here). It annotates the PR's "Files changed" tab and never blocks.
  To make any of those rules mandatory, add them to `select` under
  `[tool.ruff.lint]` in `pyproject.toml` and they become part of `make lint`.

If the team still wants Qlty later, the exact steps are:

1. Owner logs in at https://qlty.sh with the personal GitHub account and
   installs the app on the repo.
2. In the workflow's `coverage` job, add after the pytest step:

   ```yaml
   - run: uv run --with coverage coverage xml
   - uses: qltysh/qlty-action/coverage@v2
     with:
       oidc: true
       files: coverage.xml
   ```

   and give that job `id-token: write`. Nothing else in this repo changes.
