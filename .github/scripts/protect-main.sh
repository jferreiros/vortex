#!/usr/bin/env bash
# Require the CI `gate` check before anything merges into main.
#
# Run once, as the repo owner, with the PERSONAL gh login (jferreiros):
#   gh auth status            # must show jferreiros, not the work profile
#   bash .github/scripts/protect-main.sh
#
# What it sets:
#   - required status check: the `gate` job of .github/workflows/ci.yml,
#     and the branch must be up to date with main before merging (strict)
#   - no force pushes, no branch deletion
#   - enforce_admins=false: the owner keeps `gh pr merge --admin` as the
#     4 a.m. escape hatch (see docs/ci.md)
#   - no required reviews: five people, one weekend. Add later if wanted.
set -euo pipefail

REPO="${REPO:-jferreiros/vortex}"

gh api --method PUT "repos/${REPO}/branches/main/protection" \
  --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["gate"] },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": false
}
JSON

echo "main is protected. Verify with:"
echo "  gh api repos/${REPO}/branches/main/protection --jq '.required_status_checks.contexts'"
