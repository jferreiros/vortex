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
| `evals` | `make evals` (layers 1+2+4, no keys) | no, reports on the PR; `continue-on-error` |
| `gate` | green only if `test`, `lint` and `format` are green | this is the required check |

The six jobs besides `gate` run in parallel. `gate` is the single status check that
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

## Evals on CI

`make evals` (layers 1 + 2 + 4, no keys) runs on every pull request and every
push to `main`. The job is named `evals`. It never joins `gate`: a red
scoreboard must not stop a merge. `continue-on-error` keeps the workflow
green so the Discord `workflow_run` hook does not announce a CI failure when
only evals are red. The job itself still shows as failed in the Actions list
when the board is FAIL, so you can see it.

What it publishes:

- the markdown table in the job summary
- one PR comment (`<!-- vortex-evals -->`, updated in place) with solid /
  hollow / fail / broke / fixed
- artifact `evals-report` (`summary.md`, `summary.json`, `report.html`)

Discord does not get this from GitHub Actions: Discord 403s those runner IPs.
Post from a laptop or the VPS after a local run:

```bash
make evals
make evals-discord    # needs DISCORD_WEBHOOK_URL in .env
```

Layer 3 (`make evals-voice REAL=1`) stays off CI: it spends money.

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

## CodeRabbit: an advisory review on every pull request

A second workflow, `.github/workflows/coderabbit.yml`, asks CodeRabbit to
review the PR and posts the result as one comment. It advises; `gate` decides.
It is not required on `main`, the job has `continue-on-error`, and a red
CodeRabbit changes nothing about whether you can merge.

### Which integration, and why

CodeRabbit has two ways in, and they are not interchangeable:

| Path | What it needs | Who can set it up |
| --- | --- | --- |
| GitHub App | The repo owner logs in at https://app.coderabbit.ai/login with GitHub, installs the app on `jferreiros/vortex`, grants read-write on checks, code, commit statuses, issues and pull requests. No API key involved. | A person in a browser. Cannot be done by an agent or from a workflow. |
| CLI in a workflow | An **Agentic** API key (`cr-...`) from https://app.coderabbit.ai, Settings, API Keys, stored as a repository secret. | Anyone with the key, fully from the repo. |

The key the team has is a `cr-...` key, which is what the CLI takes, and the
CLI path needs nobody in a browser. So this repo uses the CLI. The key is the
repository secret `CODERABBIT_API_KEY` and is never written to a file or a log.

Two things about that key the docs are explicit on, and that only a real run
can confirm:

- It must be an *Agentic* key, not a *user* key. The CLI rejects user keys
  with "user API keys are not supported". If the first run fails that way,
  whoever owns the CodeRabbit account generates an Agentic key at
  https://app.coderabbit.ai, Settings, API Keys, and replaces the secret with
  `gh secret set CODERABBIT_API_KEY`. Nothing in the repo changes.
- Reviews are billed to the key's organisation and count against the seat's
  allowance (3 CLI reviews per hour on the free plan; paid plans more). That is
  why the workflow runs once per PR and not on every push.

### What it reviews, and when

- Runs on `pull_request` `opened`, `reopened` and `ready_for_review`. Not on
  `synchronize`, so pushing more commits does not re-run it. Not on `push`.
  Drafts are skipped.
- To re-run on the current head, add the label `re-review` to the PR. Remove
  it and add it again for another run. The existing comment is updated in
  place, so a PR never has two review comments.
- Diffs the PR head against its base branch, with `.coderabbit.yaml` and
  `CLAUDE.md` passed as instructions. The path instructions in
  `.coderabbit.yaml` restate the hard rules the reviewer must check on
  anything under `vortex/`: every call ends in a submission, never nothing;
  every `patient_id`, `appointment_id` and `appointment_type_id` comes from the
  clinic API and never from the caller or the model; no state shared between
  sockets; tools return typed data or a typed `Rejection`; time from
  `ToolContext.now`, never the machine clock; no secrets. Extra checks apply to
  `vortex/contract.py`, `vortex/tools.py`, `vortex/settings.py` (breaking
  signature changes), `vortex/line/` (per-socket pipeline, submit window),
  `tests/` (offline, no shared state) and the workflows themselves.
- Skips formatting and naming: ruff gates those already.
- Without the secret the job logs "secret not set" and exits green. So a fork
  or a clone without the key still gets a clean CI.

The CLI version is pinned in the workflow (`CODERABBIT_VERSION`). Bump it on
purpose, after reading the changelog.

### When it is wrong

It will be, sometimes. It is a reviewer, not a gate:

- Ignore the comment and merge. Nothing to override, nothing to click.
- If it flagged one of the hard rules and it is actually fine, say so in a
  reply on the PR so the next person at 3 a.m. does not re-open the question.
- If it keeps flagging the same non-issue, tighten the wording in
  `.coderabbit.yaml` under `reviews.path_instructions`. Validate the file
  before you push it:

  ```bash
  curl -fsSL https://cli.coderabbit.ai/install.sh | CI=1 sh   # once
  coderabbit config validate                                  # exit 0 = valid
  ```

  Validation needs no key. A real review does:
  `coderabbit review --base main --api-key "$CODERABBIT_API_KEY"`.
- If the job itself is red (rate limit, wrong key type, CodeRabbit down), the
  comment says so and the merge is unaffected. Fix the key or wait an hour;
  do not touch `gate`.

### How to silence it

Pick the smallest one:

| You want | Do |
| --- | --- |
| No review on this one PR | Open it as a draft and mark it ready only when done; or just ignore the comment. |
| Pause it for the weekend | `gh workflow disable coderabbit`. `gh workflow enable coderabbit` brings it back. |
| Stop it spending quota at all | `gh secret delete CODERABBIT_API_KEY`. The job then skips green on every PR. |
| Remove it | Delete `.github/workflows/coderabbit.yml` and `.coderabbit.yaml`, and this section. |

### If the team wants the GitHub App instead

The App reviews inline on the diff, replies to comments and re-reviews on
every push. It is the better product and it costs one browser session:

1. The repo owner (`jferreiros`, personal account) logs in at
   https://app.coderabbit.ai/login with GitHub and installs the app on
   `jferreiros/vortex` when asked. Permissions requested: read on actions,
   discussions, members, metadata and merge queues; read-write on checks,
   code, commit statuses, issues and pull requests.
2. Nothing in the repo changes. `.coderabbit.yaml` already sets
   `reviews.auto_review` (no drafts, no re-review on every push) and the same
   path instructions, so the App reads them as-is.
3. Then remove the CLI workflow or keep both; the App does not use the secret.
