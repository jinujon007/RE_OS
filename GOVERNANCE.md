# RE_OS Repository Governance

**Last updated:** 2026-05-19
**Owner:** @jinujon007
**Status:** Active

This document is the single source of truth for how this repository is governed.
When this document conflicts with any other file, this document wins.

---

## Branch Strategy

| Branch | Purpose | Protection |
|--------|---------|-----------|
| `master` | Production. Always deployable. | Full — see below |
| `feat/*` | New capabilities | Short-lived. Merge within 5 days. |
| `fix/*` | Bug fixes | Short-lived. Merge within 3 days. |
| `chore/*` | Maintenance, config, docs | Short-lived. Merge within 3 days. |
| `T-XXX/*` | Task-queue items (multi-brain) | Short-lived. One branch per task. |

**Branch age policy:** Any branch older than 14 days without activity is stale.
Comment on the PR or delete the branch.

---

## Merge Policy

**Default merge strategy:** Squash merge.

Every PR becomes one commit on master. The PR title becomes the commit message.
The PR body preserves the full history. This keeps `git log` on master readable
as a changelog.

**No merge commits on master.** Linear history is required.

**No direct pushes to master.** Every change goes through a PR, regardless of size.
One-line typo fix? PR. Critical hotfix? PR. No exceptions.

---

## Branch Protection Rules (master)

Currently configured at: GitHub → Settings → Branches → master

| Rule | Setting |
|------|---------|
| Require PR before merging | Enabled |
| Required approvals | 1 |
| Dismiss stale approvals on new commits | Enabled |
| Require CODEOWNERS review | Enabled |
| Required status checks | CI (lint, docker, schema), Security (trufflehog, gitleaks), PR title |
| Require branches up to date | Enabled |
| Require conversation resolution | Enabled |
| Require signed commits | Enabled (after GPG setup) |
| Require linear history | Enabled |
| Allow force pushes | Disabled |
| Allow branch deletion | Disabled |
| Bypass for admins | Disabled |

---

## PR Review Standards

| Change type | Minimum review | Expected turnaround |
|-------------|---------------|-------------------|
| Schema migration | Full review — check backward compat | 24 hours |
| LLM router change | Full review — test fallback chain | 24 hours |
| New scraper | End-to-end pipeline test required | 24 hours |
| Agent logic | Logic + fallback review | 24 hours |
| Config / env | Check for secret exposure | 4 hours |
| Docs only | CI pass sufficient | 4 hours |
| CI/CD change | Full review — break CI = break everyone | 24 hours |

---

## PR Title Convention

All PR titles must follow Conventional Commits:

```
<type>(<optional-scope>): <short description lowercase>
```

**Allowed types:**
- `feat` — new capability
- `fix` — bug fix
- `chore` — maintenance, no behavior change
- `docs` — documentation
- `refactor` — code restructuring, no behavior change
- `test` — test additions
- `ci` — CI/CD changes
- `perf` — performance improvement
- `build` — build system or dependency changes
- `revert` — reverts a previous commit

**Examples:**
```
feat: yelahanka RERA scraper — AJAX intercept with POST fallback
fix: cerebras fallback uses prompt not filtered[:2000]
chore: bump ruff 0.4.4 → 0.5.0
ci: add trufflehog secret scan to security workflow
docs: add GPG signing setup to GOVERNANCE.md
```

PR title validation is enforced by `.github/workflows/pr-title-check.yml`.
Non-conforming titles block the PR.

---

## CI/CD Gates

All of the following must pass before any PR can merge:

**Workflow: CI (`ci.yml`)**
- `Lint & Syntax Check` — ruff + py_compile on all source files
- `Docker Compose Validate` — validates docker-compose.yml against stub .env
- `SQL Schema Syntax` — applies schema.sql to a fresh PostGIS test instance

**Workflow: Security Scan (`security.yml`)**
- `Secret Scan (TruffleHog)` — scans full commit history for verified secrets
- `Secret Scan (Gitleaks)` — secondary secret scan with different detection patterns

**Workflow: PR Title Check (`pr-title-check.yml`)**
- `Conventional Commit Title` — validates PR title format

**Workflow: Dependency Review (`dependency-review.yml`)**
- `Dependency Vulnerability Review` — blocks HIGH/CRITICAL CVEs and incompatible licenses

Failing any gate blocks the merge. There is no bypass except disabling branch protection,
which requires an incident record (see Emergency Bypass below).

---

## Release Process

**Versioning:** Semantic versioning. `MAJOR.MINOR.PATCH`

- `MAJOR` — breaking schema change, architecture change, or incompatible API change
- `MINOR` — new scraper, new market, new agent capability
- `PATCH` — bug fix, config change, dependency update

**Release steps:**
```powershell
# 1. Confirm master is clean and CI is green
git pull origin master
git status  # should be clean

# 2. Tag the release
git tag -a v0.2.0 -m "feat: Hebbal scraper + developer scorecard view"
git push origin v0.2.0

# 3. GitHub Release is auto-created by release.yml
# 4. Verify at: github.com/jinujon007/RE_OS/releases
```

The `release.yml` workflow auto-generates release notes from merged PR titles since the last tag.
This is why PR title convention matters — it becomes the changelog.

---

## Emergency Bypass Protocol

When master must be fixed faster than the PR process allows:

1. **Create an incident issue** before touching anything.
   Title: `[INCIDENT] Short description — bypass required`
2. **Temporarily disable branch protection** (Settings → Branches → master → Edit → save without protections)
3. **Push the fix directly.** Document the commit SHA in the incident issue.
4. **Re-enable branch protection immediately.** Do not leave it disabled.
5. **Post-mortem within 48 hours.** Comment on the incident issue: what happened, what broke, how it was fixed, how to prevent it.

The GitHub audit log records every protection disable/enable event.
This is not a workaround — it is a formal incident procedure.

**Track all bypasses:** https://github.com/jinujon007/RE_OS/issues?q=label%3Aincident

---

## Label Management

Labels are defined in `.github/labels.yml`.

To sync labels to GitHub:
```powershell
# Install GitHub CLI if not present: winget install --id GitHub.cli
# Authenticate: gh auth login

# Sync all labels from labels.yml (creates missing, updates existing, does NOT delete extra)
Get-Content .github/labels.yml | python -c "
import sys, yaml, subprocess
labels = yaml.safe_load(sys.stdin)
for label in labels:
    subprocess.run([
        'gh', 'label', 'create', label['name'],
        '--color', label['color'],
        '--description', label.get('description', ''),
        '--force'
    ])
"
```

Or one-by-one:
```powershell
gh label create "P0-critical" --color "d73a4a" --description "Production-breaking." --force
```

---

## Secrets Management

1. **Zero secrets in git.** `.env` is gitignored. `.env.example` contains only placeholder values.
2. **Secret scanning runs on every PR and push.** TruffleHog + Gitleaks.
3. **If a secret is detected in history:** Rotate the key immediately (assume compromised). Contact GitHub support to purge history if needed. Do not rely on rewriting history alone — treat it as public.
4. **Key rotation procedure:** Update `.env` → `docker compose restart agents scheduler` (no rebuild needed).
5. **GitHub-native secret scanning:** Enable at Settings → Security → Secret scanning. Free for public repos.

---

## Dependency Governance

- Dependabot checks weekly (Mondays) for pip + GitHub Actions updates.
- PRs for patch/minor updates should be merged promptly (they carry security fixes).
- Major bumps for `crewai`, `crewai-tools`, `sqlalchemy` are blocked by Dependabot config — review manually.
- Dependency review action blocks HIGH/CRITICAL CVEs from merging.

---

## Commit Signing

All commits on master must be GPG-signed after initial setup.

**Setup:**
```powershell
# Generate GPG key
gpg --full-generate-key
# Choose: RSA and RSA, 4096 bits, no expiry (or 2 years for security)

# Get key ID
gpg --list-secret-keys --keyid-format=long

# Configure git
git config --global user.signingkey YOUR_KEY_ID
git config --global commit.gpgsign true
git config --global tag.gpgsign true

# Export and add to GitHub
gpg --armor --export YOUR_KEY_ID
# GitHub → Settings → SSH and GPG keys → New GPG key → paste
```

---

## Governance Review Cadence

| Review type | Frequency | What to check |
|-------------|-----------|---------------|
| Branch hygiene | Weekly | Branches older than 14 days? |
| Open PR triage | Weekly | PRs older than 7 days? |
| Dependabot PRs | Weekly | Merge or close pending updates |
| CI health | Per merge | Any flaky jobs? |
| Security alerts | Monthly | GitHub Security tab |
| Label audit | Monthly | Labels referenced but undefined? |
| Protection config | Quarterly | Rules still match team maturity? |

---

## Governance Maturity Targets

| Phase | Target date | Criteria |
|-------|-------------|----------|
| Phase 1 — Solo Baseline | 2026-05-26 | Branch protection on, CI gates active, secret scan running |
| Phase 2 — Process Hardened | 2026-06-30 | Signed commits, first release tagged, stale branches cleared |
| Phase 3 — Scaled | When team > 2 | 2 required approvals, team-based CODEOWNERS, SAST added |
