# Kaveri Karnataka Jurisdiction Reference
Source: github.com/zen-citizen/scraps (zen-citizen/scraps, GPL-3.0)
Downloaded: 2026-06-12
Scope: Complete Karnataka — all districts, taluks, hoblis, villages as per Kaveri Online Services

## Files

| File | Description | Size |
|------|-------------|------|
| district_talukas.json | District → Taluks mapping | 31 KB |
| taluk_hoblis.json | Taluk → Hoblis mapping | 241 KB |
| hobli_villages.json | Hobli → Villages mapping | 12506 KB |
| village_mapping.json | Village code → metadata | 2962 KB |
| remap.json | Flat: village → district/taluk/hobli (fastest lookup) | 4921 KB |
| karnataka_full_hierarchy.json | Full nested: district→taluk→hobli→villages | 5623 KB |
| bangalore_hierarchy.json | Bangalore Urban + Rural only | 194 KB |
| village_lookup_index.json | village_name (lower) → [district, taluk, hobli] | 5520 KB |
| yelahanka_hobli_villages.json | Yalahanka Hobli — 25 villages for Sprint 91 | - |

## Stats
- Karnataka: 35 districts | 225 taluks | 1102 hoblis | 50511 villages
- Bangalore subset: 1 districts | 4 taluks | 25 hoblis | 1719 villages

## Usage

```python
import json

# Find which hobli a village belongs to
with open("data/kaveri_jurisdiction/village_lookup_index.json") as f:
    idx = json.load(f)
result = idx.get("jakkur", [])  # always lowercase

# Get all villages in a hobli
with open("data/kaveri_jurisdiction/hobli_villages.json") as f:
    hoblis = json.load(f)
villages = hoblis["Yalahanka Hobli"]

# Traverse Bangalore hierarchy
with open("data/kaveri_jurisdiction/bangalore_hierarchy.json") as f:
    blr = json.load(f)
yelahanka_hoblis = blr["Bangalore Urban"]["Bangalore North"]
```

## Notes
- Kaveri spells "Yelahanka" as **"Yalahanka"** — use this exact spelling in API calls
- village_lookup_index keys are lowercased for case-insensitive search
- remap.json is the fastest file for reverse lookups (village → district/taluk/hobli)
