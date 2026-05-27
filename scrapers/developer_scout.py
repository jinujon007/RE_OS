"""
RE_OS — Developer Scout
────────────────────────
Goes directly to developer websites — not the portals, not RERA.
This is the "street intelligence" layer. Developer sites often carry:
  • Pre‑launch projects (not yet on portals or RERA)
  • Soft‑launch pricing (before official listing)
  • Phase‑wise updates (Phase 2 launch while Phase 1 is on portals)
  • Micro‑market expansion signals (when a developer enters a new zone)

Covered developers (North Bengaluru focus):
  Brigade Enterprises, Prestige Group, Sobha Limited, Godrej Properties,
  Adarsh Developers, Salarpuria Sattva, Shriram Properties, Mantri Developers

Model : Gemini Flash — handles unstructured developer‑marketing pages better
       than structured extraction models. Large context = full‑page comprehension.

Market filter : Each developer’s project list is filtered for North Bengaluru
keywords (yelahanka, hebbal, devanahalli, jakkur , kog …)

Dedup : canonical ID = dev:{sha16(developer+name+locality)} --- cross‑source.
         … …