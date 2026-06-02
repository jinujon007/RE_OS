# IGR Karnataka Portal — Integration Spec (T-791)

_Author: Kilo Code_
_Date: 2026-06-02_
_Prerequisite for: T-792 (IGR scraper rewrite)_

---

## 1. Objective

Document the exact HTTP request structure for the Karnataka IGR portal sale-deed search so `scrapers/igr_karnataka.py` can be rewritten with a proven request payload instead of guesswork.

**This file is a specification only. No code in this repository depends on the URLs or parameters below until T-792 implements them.**

---

## 2. Portal Endpoints Observed

| Endpoint | Method | Purpose | Status |
|----------|--------|---------|--------|
| `https://kaveri.karnataka.gov.in/` | GET | Portal home | Responsive |
| `https://kaveri2.karnataka.gov.in/kaverireports/` | GET | Kaveri reports mirror | Responsive |
| `https://kaveri.karnataka.gov.in/registration/search` | GET/POST | Sale deed registration search | **Target** |
| `https://kaveri.karnataka.gov.in/kaveriimages/` | GET | Document images (encumbrance certs) | Not tested |

> **Important:** The IGR search appears to be a sub-module of the Kaveri portal. The URL path `/registration/search` is inferred from the portal navigation structure and has **not** been confirmed with a live request yet.

---

## 3. Request Structure (Best-Effort Hypothesis)

### 3.1 Initial GET (to obtain session / CSRF)

```
GET https://kaveri.karnataka.gov.in/registration/search
Headers:
  User-Agent: <current Chrome UA>
  Accept: text/html,application/xhtml+xml
  Referer: https://kaveri.karnataka.gov.in/
```

**Expected response:** HTML form with hidden CSRF token field (name likely `_csrf` or similar).

**Action on success:**
- Parse CSRF token from `<meta>` or `<input type="hidden">`
- Store session cookies for subsequent POST

### 3.2 Search POST

```
POST https://kaveri.karnataka.gov.in/registration/search
Headers:
  Content-Type: application/x-www-form-urlencoded
  X-Requested-With: XMLHttpRequest   (if AJAX)
  Referer: https://kaveri.karnataka.gov.in/registration/search
Body (form-encoded):
  district     = <DISTRICT_ID or NAME>    (e.g. "Bangalore Urban" or numeric ID)
  taluk        = <TALUK_NAME>             (e.g. "Bangalore North")
  village      = <VILLAGE_NAME>           (optional)
  fromDate     = DD/MM/YYYY               (30 days ago)
  toDate       = DD/MM/YYYY               (today)
  transactionType = "SALE"                 (sale deed type)
  _csrf        = <token from GET>         (if present)
  submit       = Search
```

**Expected response:** JSON or HTML table of registration records.

### 3.3 Response Schema (Expected Fields)

```json
{
  "records": [
    {
      "registrationNumber": "2024-25-001234",
      "surveyNo": "45/2",
      "sellerName": "Ramesh Kumar",
      "buyerName": "Suresh Enterprises",
      "considerationAmount": 15000000,
      "areaSqft": 43560,
      "registrationDate": "2025-03-15",
      "sroOffice": "Bangalore North",
      "propertyType": "Residential",
      "status": "Registered"
    }
  ],
  "totalRecords": 42,
  "page": 1,
  "pageSize": 25
}
```

> **Note:** This schema is a hypothesis based on standard IGR portal patterns and the `igr_transactions` table columns. Actual field names may differ.

---

## 4. District/Taluk Mapping (from T-475)

Derived from `IGR_MARKET_META` in `scrapers/igr_karnataka.py`:

| Market | District | Taluk |
|--------|----------|-------|
| Yelahanka | Bangalore Urban | Bangalore North |
| Devanahalli | Bangalore Rural | Devanahalli |
| Hebbal | Bangalore Urban | Bangalore North |

These are **string values** used in form fields. Numeric district IDs (if required) must be discovered via T-792 live probing.

---

## 5. Test Plan for T-792

1. **GET probe**: `curl -I` the search URL — confirm 200 response
2. **Form inspection**: fetch HTML, grep for `<form>` action, input names, CSRF token
3. **POST dry-run**: send minimal form body (district + dates only), observe response code + body
4. **Parameter alignment**: compare response fields to `igr_transactions` table columns
5. **SRO disambiguation**: if multiple SRO offices share a taluk, add `sroOffice` filter

---

## 6. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Portal URL structure changed since T-475 | Medium | High | T-792 probes live first; falls back to confirmed hardcoded data |
| CSRF token required | High | Medium | Two-step GET→POST with token extraction |
| Response is HTML table not JSON | Medium | Medium | T-792 parses both; Happy path documented here |
| District IDs are numeric not strings | Medium | Medium | Probe with both formats; mapping table in T-792 |
| Portal blocks non-browser User-Agents | Medium | Low | Use Scrapling TLS spoof (proven pattern from portal_scout) |
| Rate limiting / CAPTCHA | Medium | Medium | 3-second delay between requests; fallback to seeded data |

---

## 7. What This Spec Does NOT Cover

- Live test results (T-792 will fill these in)
- Exact CSRF token field name
- Actual response schema (validated during T-792)
- Authentication / session requirements beyond initial GET

**Next action:** T-792 opens the portal in DevTools → Network tab, captures the actual POST, updates this spec with confirmed values, then implements.
