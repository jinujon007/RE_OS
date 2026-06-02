# RE_OS Strategy
<!-- Used by /ce-strategy, /ce-ideate, /ce-brainstorm, /ce-plan as grounding anchor -->
<!-- Keep this short. Update with /ce-strategy when direction shifts. -->

## Target Problem
LLS enters land acquisition and micro-market positioning decisions with less structured intelligence than Grade A developers. The fog between "we think Yelahanka is ready" and "here is the evidence" costs months and mispriced land bids.

## Approach
A multi-agent pipeline that continuously scrapes RERA Karnataka, listing portals, Kaveri/IGR registrations, and developer sites — then runs 5-department Board Room analysis (BD / Finance / Engineering / Ops / Legal) to produce a go/no-go verdict with supporting data. Not a dashboard for its own sake — a decision engine that cuts the research cycle from weeks to minutes.

## Persona (Primary User)
Jinu — LLS employee, solo operator. Reads Board Room output to decide: enter this micro-market at what PSF? Which competitors to watch? Which developers are distressed (JD/JV targets)? One person, high-stakes decisions, needs conviction not just data.

## Key Metrics
- RERA live project count: ≥50 per micro-market before signals are trusted (Yelahanka 165 ✅, Devanahalli 317 ✅, Hebbal 736 ✅)
- Board Room verdict latency: <5 min from run to structured output
- IGR transaction freshness: ≤7 days old
- Test coverage: ≥55% (GATE-7 ✅)
- Distressed developer alert: fires within 30s of scrape trigger

## Active Tracks
| Track | Status | Next gate |
|-------|--------|-----------|
| Sprint 39 — Data Foundation | 🔴 ACTIVE | GATE-25: IGR live + distressed dev alert + months_of_supply |
| v2 Architecture | 🔴 PLANNED | GATE-44: 20-table schema live (Sprints 60–66) |
| HF Sprints 34–38 | ⏸ DEFERRED | After v2 Phase 5 |
| Discord Alerts (Phase 7) | 🟡 CODE DONE | GATE-14: live Discord verification |

## Hard Constraints
- Zero-cost LLM API tier only (Groq, Cerebras, Gemini, SambaNova, NVIDIA, Cloudflare, Ollama)
- RTX 3050 4GB VRAM — 7B Q4 max for GPU inference
- All data stays private — no dataset publishing
- Clean approvals only in scrapers — no grey-area data access
