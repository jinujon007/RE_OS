# CE + gstack Integration Map — RE_OS
<!-- When to use Compound Engineering vs gstack. Both installed. Best of both. -->

## Always CE

| Job | Command | Why |
|-----|---------|-----|
| Codify sprint learnings | `/ce-compound` | Nothing in gstack does this. Run after EVERY gate closes. |
| Strategy anchor | `/ce-strategy` | Maintains STRATEGY.md — CE reads it before every plan |
| Code review (PR) | `/ce-code-review` | 20+ persona agents, confidence-gated, dedup. Stronger than gstack /code-review |
| Requirements before planning | `/ce-brainstorm` | Interactive Q&A → right-sized requirements doc. Run before v2 arch planning |
| Systematic bug fix | `/ce-debug` | Reproduces failure → hypothesis → test-first fix. Use when bug has clear symptom |
| Health snapshot | `/ce-product-pulse` | Scraper success, GATE status, IGR freshness, RERA counts. Run weekly |
| Sprint execution | `/ce-work` | Worktree-based task execution. Cleaner than ad-hoc branch work |
| Commit + PR | `/ce-commit-push-pr` | Value-communicating message + PR description |
| Refresh stale learnings | `/ce-compound-refresh` | Quarterly — marks outdated compound notes |
| Multi-file simplify | `/ce-simplify-code` | Parallel reviewers + fixes applied. After big sprints |
| Doc audit | `/ce-doc-review` | Multiple lenses on CLAUDE.md, VISION.md, TASK_QUEUE.md |
| Past session context | `/ce-sessions` | Query session history for sprint continuity |
| Git worktrees | `/ce-worktree` | Parallel sprint branches |

## Always gstack

| Job | Command | Why |
|-----|---------|-----|
| Web browsing | `/browse` | ALWAYS gstack. Never use agent-browser directly. |
| Multi-role plan review | `/autoplan` | CEO + design + eng + DX in one pass. RE_OS domain context baked in |
| Engineering plan review | `/plan-eng-review` | Domain-specific lens — not generic like CE |
| Investigate complex bug | `/investigate` | Full codegraph + codebase context. Better for multi-file systemic bugs |
| QA / test runs | `/qa` | Structured test matrix |
| Verify change works | `/verify` | Runs real app and observes behavior |
| Launch stack | `/run` | Starts RE_OS docker stack |
| Deploy | `/ship` | Deployment pipeline with canary |
| RE_OS DB check | `/check-db` | Custom skill — postgres MCP |
| Run crew | `/run-crew` | Custom skill — market intel pipeline |
| Live log | `/tail-log` | Custom skill |
| Big-picture plan review | `/plan-ceo-review` | Investor/strategic lens |

## Overlaps — Which Wins

| Overlap | Winner | Rule |
|---------|--------|------|
| Code review | CE `/ce-code-review` | Richer agents, confidence gating |
| Simplify code | Either | Equivalent. CE if post-sprint sweep, gstack /simplify for quick pass |
| Bug investigation | gstack `/investigate` if codebase-wide, CE `/ce-debug` if specific symptom | |
| Planning | gstack `/autoplan` for RE_OS phases, CE `/ce-brainstorm`+`/ce-plan` for new features | |
| Commit | CE `/ce-commit-push-pr` | Better messages |

## Sprint Rhythm (recommended)

```
Sprint start:    /ce-sessions          ← recall last sprint context
                 /ce-strategy          ← check STRATEGY.md is still accurate
Planning:        /ce-brainstorm        ← requirements doc for new feature/phase
                 /autoplan             ← multi-role plan review (gstack)
Execution:       /ce-work              ← worktree-based sprint tasks (Kilo does impl)
Mid-sprint:      /investigate          ← when bugs block (gstack)
                 /ce-debug             ← when symptom is clear (CE)
Pre-gate:        /ce-code-review       ← PR review before merging
                 /ce-simplify-code     ← cleanup pass
Post-gate:       /ce-compound          ← MANDATORY: codify what was solved
Weekly:          /ce-product-pulse     ← RE_OS health snapshot
Quarterly:       /ce-compound-refresh  ← refresh stale learnings
```
