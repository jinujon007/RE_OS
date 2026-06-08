# Security Policy

## Scope

RE_OS is an internal intelligence platform operated by Land & Life Space (LLS),
Bengaluru. It is not a public service. Port 8050 is never intentionally exposed
to the public internet.

## Supported Versions

Only the current `master` branch receives security fixes.

## Reporting a Vulnerability

If you discover a security issue:

1. **Do not open a public GitHub issue.**
2. Email **jinujon007@gmail.com** with subject line `[RE_OS SECURITY] <brief title>`.
3. Include: description, reproduction steps, impact assessment, and any proposed fix.
4. You will receive an acknowledgement within 72 hours.
5. If confirmed, a fix will be shipped in the next sprint. You will be credited in
   the CHANGELOG unless you prefer to remain anonymous.

## Known Deployment Constraints

- `DASHBOARD_API_KEY` must be set before port 8050 is accessible. The server
  refuses to start without it unless `DASHBOARD_API_KEY_ALLOW_EMPTY=true` is
  explicitly set (local dev only).
- All inter-container traffic is on an internal Docker network. Only port 8050
  is mapped to the host.
- API key rotation uses the `DASHBOARD_API_KEY_PREV` dual-key window to avoid
  downtime during rotation.
