# Security Policy

## Supported Versions

RE_OS is actively developed on `master`. Only the latest commit is supported.

| Branch | Supported |
|--------|-----------|
| master (latest) | ✅ |
| Older commits | Not supported |

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email: jinujon007@gmail.com

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

Expected response time: 5 business days.

---

## Scope

Security concerns relevant to this project:

- **API key exposure** — code that could leak keys from `.env` to logs, outputs, or version control
- **Scraper SSRF** — scrapers that follow redirects to internal network addresses
- **SQL injection** — any user-controlled string passed to raw SQL queries
- **Docker escape** — container configuration that allows host filesystem access beyond the project directory

Out of scope:
- Rate-limit bypass on third-party RERA/listing portals (this is a research tool, not a commercial scraper)
- Denial-of-service against the local Docker stack (you own the machine)

---

## Security Design Notes

- `.env` is gitignored and never committed. `.env.example` contains only placeholder values.
- All DB queries use parameterised statements via SQLAlchemy (no raw f-string SQL).
- Playwright runs in headless Docker with no host network access.
- The dashboard (`dashboard/app.py`) runs on port 8050 inside Docker. All market parameters on
  pipeline-control and report endpoints are validated against a strict whitelist before any
  filesystem or subprocess operation is performed.
- The agents container runs as a non-root user (`re_os`, uid 1001) since Dockerfile v1.1.
