## T-039 | Diagnose developer_scout.py — root cause for 0 projects | DONE | 2026-05-15 18:24

**Findings:**
- North Bengaluru keywords for Brigade: ["yelahanka", "jakkur", "hebbal", "kogilu", "thanisandra", "north bangalore", "devanahalli", "bagalur"]
- North Bengaluru keywords for Prestige: ["yelahanka", "hebbal", "devanahalli", "north bangalore", "thanisandra", "jakkur", "finsbury"]
- Brigade website URL: "https://www.brigade.in/all-properties?city=bangalore" (with alt_url: "https://www.brigade.in/residential")
- Prestige website URL: "https://www.prestige.co.in/residential-projects/bangalore" (with alt_url: "https://www.prestige.co.in/all-projects")
- Playwright CSS selector: No specific CSS selector used - fetches entire page content
- Minimum match threshold: No explicit threshold found in code
- Likely issue: _clean_html function removes nav/header/footer/tags where keywords may reside, resulting in zero matches after cleaning

**Status change:** T-039 → DONE