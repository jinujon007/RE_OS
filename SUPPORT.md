# Support

## Before Filing an Issue

1. **[HOW_TO_RUN.md](HOW_TO_RUN.md)** — covers every common setup error, Docker issue, and scraper failure with exact fixes. Check here first.
2. **[GitHub Discussions](https://github.com/jinujon007/RE_OS/discussions)** — for questions, output sharing, and market coverage discussion.

---

## Reporting Bugs

Use the [Bug Report template](https://github.com/jinujon007/RE_OS/issues/new?template=bug_report.yml).

Always include:

```bash
docker compose logs agents --tail 50
docker compose ps
```

The exact error line matters more than your interpretation of it. Log paste > description.

---

## Feature Requests

Use the [Feature Request template](https://github.com/jinujon007/RE_OS/issues/new?template=feature_request.yml).

Read [VISION.md](VISION.md) first. Most meaningful features are already in the 14-phase roadmap — if your idea fits an existing phase, reference it.

---

## Response Time

Solo-maintained project. Responses are best-effort. Prioritization:

1. Bugs blocking Stage 1–3 pipeline execution
2. Database schema issues
3. LLM routing failures
4. Feature requests with a draft PR attached

---

## Out of Scope

- Support for RERA states other than Karnataka — open a PR, don't open an issue
- API key quota support for Groq, Cerebras, NVIDIA, etc. — contact those providers directly
- General Docker or Python environment help beyond what HOW_TO_RUN.md covers
