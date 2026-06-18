# Corridor Scorer v1 — Backtest Report
**Generated:** 2026-06-17T14:29:06.678580+00:00
**Train window:** 2024-01-01 → 2024-06-30
**Test window:** 2024-07-01 → 2024-12-31

## Verdict
**INSUFFICIENT_DATA** — Only 0 of 3 corridors have registered deed data in the backtest windows. Need ≥2 corridors with transactions in both train and test windows. Re-run after more Form 17 PDFs are ingested.

## Train-Window Scores (Jan–Jun 2024)

| Corridor | Composite | Velocity | PSF Trend | GCC | Infra | Txns | Avg PSF |
|----------|-----------|----------|-----------|-----|-------|------|---------|
| NH-44 (Yelahanka → Devanahalli) | 3.50 | 0.0 | 5.0 | 5.0 | 5.0 | 0 | N/A |
| Hebbal–Yelahanka Inner Road | 3.50 | 0.0 | 5.0 | 5.0 | 5.0 | 0 | N/A |
| Doddaballapur Road | 3.50 | 0.0 | 5.0 | 5.0 | 5.0 | 0 | N/A |

## Actual PSF Appreciation (Jul–Dec 2024 vs Jan–Jun 2024)

| Corridor | Train PSF | Test PSF | Appreciation % |
|----------|-----------|----------|----------------|
| NH-44 (Yelahanka → Devanahalli) | N/A | N/A | N/A |
| Hebbal–Yelahanka Inner Road | N/A | N/A | N/A |
| Doddaballapur Road | N/A | N/A | N/A |

## Notes

### NH-44 (Yelahanka → Devanahalli)
- velocity query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8)
- PSF trend query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8)
- GCC query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8) — neutral score 5.0
- Infra query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8) — neutral score 5.0

### Hebbal–Yelahanka Inner Road
- velocity query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8)
- PSF trend query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8)
- GCC query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8) — neutral score 5.0
- Infra query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8) — neutral score 5.0

### Doddaballapur Road
- velocity query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8)
- PSF trend query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8)
- GCC query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8) — neutral score 5.0
- Infra query failed: (psycopg2.OperationalError) connection to server at "localhost" (::1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?
connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused (0x0000274D/10061)
	Is the server running on that host and accepting TCP/IP connections?

(Background on this error at: https://sqlalche.me/e/20/e3q8) — neutral score 5.0

## Kill Criterion Check

Per V2 audit §8: scorer must beat distance-to-airport by ≥20% rank accuracy (67% rank correlation threshold on 3 corridors).

Current status: **INSUFFICIENT_DATA**

Re-run after ≥10 Sale deeds per corridor per window are ingested from Form 17 PDFs.