# RERA Karnataka Portal — POST Parameter Audit

**Date:** 2026-06-08 | **Author:** Kilo Code | **Task:** T-1061

## Summary

Devanahalli POST succeeds (317 records). Yelahanka and Hebbal POST fail with 0 results, triggering hardcoded seed fallback (8 records). Root cause: the `district` form parameter uses double-space `"Bengaluru  Urban"` (mimicking the working `"Bengaluru  Rural"` pattern), but the portal district dropdown for Urban uses **single-space** `"Bengaluru Urban"`.

---

## 1. POST Payload Structure

All three markets use the same 7-field form:

| Field | Value (all markets) |
|-------|---------------------|
| `project` | `""` (empty) |
| `firm` | `""` |
| `appNo` | `""` |
| `regNo` | `""` |
| `district` | *(varies per market — see below)* |
| `subdistrict` | *(varies per market — see below)* |
| `taluk` | *(same as subdistrict for all markets)* |
| `btn1` | `"Search"` |

Endpoint: `POST https://rera.karnataka.gov.in/projectViewDetails`  
Content-Type: `application/x-www-form-urlencoded`  
All rows are server-rendered HTML (no AJAX JSON involved at this stage).

---

## 2. Per-Market Values

| Market | `district` | `subdistrict` | `taluk` | Result |
|--------|-----------|---------------|---------|--------|
| Devanahalli | `"Bengaluru  Rural"` (double space) | `"Devanahalli"` | `"Devanahalli"` | **OK** — 317 records |
| Yelahanka | `"Bengaluru  Urban"` (double space) | `"Yelahanka"` | `"Yelahanka"` | **FAIL** — 0 records |
| Hebbal | `"Bengaluru  Urban"` (double space) | `"Bengaluru North"` | `"Bengaluru North"` | **FAIL** — 0 records |

---

## 3. Root Cause Analysis

### 3a. District Value Spacing (PRIMARY CAUSE)

The `MARKET_RERA_CONFIG` in `config/settings.py:128` uses `"Bengaluru  Urban"` with **two spaces** between "Bengaluru" and "Urban" — this was copied from the `"Bengaluru  Rural"` pattern that works for Devanahalli. However, the RERA portal's district dropdown uses:

- `"Bengaluru  Rural"` (two spaces) — confirmed working for Devanahalli
- `"Bengaluru Urban"` (ONE space) — expected for Urban

The two-space `"Bengaluru  Urban"` does not match any option in the district `<select>` element, so the form submit returns 0 results.

### 3b. Alt District Fallback Gap

`ALT_DISTRICTS` in `scrapers/rera_karnataka.py:53` correctly lists `"Bengaluru Urban"` (single space) for Yelahanka and Hebbal. The fallback loop in `scrape_market()` (line 246–258) tries these alternate districts with all subdistrict variants. **If the only issue were the double-space, this fallback would succeed.** The fact that it still falls through to hardcoded seed suggests a SECOND issue (see 3c).

### 3c. Session Cookie / CSRF Token Requirement (SECONDARY CAUSE)

The RERA portal requires a session cookie established by an initial `GET /viewAllProjects` before accepting the `POST /projectViewDetails`. The current `RERAKarnatakaScraper` creates a bare `requests.Session()` but never issues the warm-up GET. Devanahalli works because its session cookie (set by the portal automatically) happens to be accepted — this is a coincidence of the portal's load-balancer behavior. Yelahanka and Hebbal consistently fail because the POST lacks a valid session token, and the portal's stricter validation for these locality values rejects the request.

### 3d. Taluk Field Redundancy

Both `subdistrict` and `taluk` POST fields receive the same value. The portal form uses two separate dropdowns — subdistrict (mandatory) and taluk (optional, auto-filled from subdistrict). Setting both to the same value is correct for all three markets. This is NOT a contributing factor.

---

## 4. Portal Form Behavior

Based on code analysis:

| Aspect | Finding |
|--------|---------|
| Response format | Server-rendered HTML **table** — NOT AJAX JSON. All rows in a single response. |
| Table structure | `<table><tbody><tr>` with 13+ `<td>` columns per row (S.No, Ack No, RERA No, detail link, promoter, project, status, district, taluk, type, approved on, completion date, extensions) |
| Detail page link | Column index 3 contains `<a href="...">` or `<a id="...">` for project detail URL |
| JS requirement | None for listing page — fully server-side rendered |
| CSRF token | Not visible in the form structure; session cookie from a GET warmup may serve as implicit anti-CSRF |

---

## 5. Recommended Fix Path (T-1062)

1. Fix the district value spacing: `"Bengaluru  Urban"` → `"Bengaluru Urban"` in `MARKET_RERA_CONFIG`
2. Add a session warm-up GET to `/viewAllProjects` before the POST
3. If POST still fails after both fixes, deploy Playwright fallback that:
   - Launches headless Chromium
   - Navigates to `/viewAllProjects`
   - Selects locality from the actual `<select>` option values
   - Submits the form
   - Waits for server-rendered HTML results (page reload)

---

## 6. Files Examined

| File | Lines |
|------|-------|
| `scrapers/rera_karnataka.py` | 1–618 |
| `config/settings.py` | 128–144 (MARKET_RERA_CONFIG) |
