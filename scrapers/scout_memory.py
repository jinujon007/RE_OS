"""
RE_OS — Scout Memory (Deduplication Engine)
─────────────────────────────────────────────
Every scout reports here before returning findings.
Already-seen items are not re-surfaced. New items are logged and flagged.
Price/status changes on known items are also detected.

Storage:
  outputs/{market}/scout_memory.json      — seen-items index (key=cid)
  outputs/{market}/scout_discoveries.jsonl — append-only new-finds log

Canonical ID (cid) strategy:
  RERA registered   → "rera:{rera_number}"          (government-issued, unique)
  Named project     → "proj:{sha16(dev+name+loc)}"  (cross-source match)
  Portal listing    → "list:{source}:{sha16(url)}"  (source-specific unit)
  Developer site    → "dev:{sha16(dev+name+loc)}"   (pre-RERA projects)
  News article      → "news:{sha16(url)}"            (market intelligence)
"""

import hashlib
import json
import os
from datetime import datetime
from loguru import logger


class ScoutMemory:
    def __init__(self, market: str, base_dir: str | None = None):
        self.market = market
        if base_dir is None:
            base_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "outputs", market.lower().replace(" ", "_")
            )
        os.makedirs(base_dir, exist_ok=True)
        self._mem_path = os.path.join(base_dir, "scout_memory.json")
        self._log_path = os.path.join(base_dir, "scout_discoveries.jsonl")
        self._idx: dict[str, dict] = self._load()
        logger.debug(f"[ScoutMemory] {market}: {len(self._idx)} items known")

    # ── CID builders ──────────────────────────────────────────────────────────

    @staticmethod
    def cid_rera(rera_number: str) -> str:
        return f"rera:{rera_number.strip()}"

    @staticmethod
    def cid_project(developer: str, name: str, locality: str) -> str:
        key = f"{developer.lower().strip()}::{name.lower().strip()}::{locality.lower().strip()}"
        return "proj:" + hashlib.sha256(key.encode()).hexdigest()[:16]

    @staticmethod
    def cid_listing(source: str, url_or_id: str) -> str:
        h = hashlib.sha256(url_or_id.strip().lower().encode()).hexdigest()[:16]
        return f"list:{source}:{h}"

    @staticmethod
    def cid_developer(developer: str, name: str, locality: str) -> str:
        key = f"dev::{developer.lower().strip()}::{name.lower().strip()}::{locality.lower().strip()}"
        return "dev:" + hashlib.sha256(key.encode()).hexdigest()[:16]

    @staticmethod
    def cid_news(url: str) -> str:
        h = hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]
        return f"news:{h}"

    # ── Core API ──────────────────────────────────────────────────────────────

    def is_known(self, cid: str) -> bool:
        return cid in self._idx

    def record(self, cid: str, data: dict, source: str = "") -> bool:
        """
        Record a finding. Returns True if new discovery, False if already known.
        New items are written to the discovery log for audit.
        """
        data_hash = self._data_hash(data)
        now = datetime.now().isoformat()

        if cid in self._idx:
            entry = self._idx[cid]
            entry["last_seen_at"] = now
            entry["times_seen"] = entry.get("times_seen", 1) + 1
            entry["data_hash"] = data_hash
            self._save()
            return False

        self._idx[cid] = {
            "cid": cid,
            "source": source,
            "market": self.market,
            "first_seen_at": now,
            "last_seen_at": now,
            "times_seen": 1,
            "data_hash": data_hash,
            "label": self._label(data),
        }
        self._log_new(cid, data, source, now)
        self._save()
        return True

    def mark_all(self, findings: list[dict], source: str = "") -> tuple[list[dict], list[dict]]:
        """
        Process a batch of findings. Records each, sets is_new flag.
        Returns (new_findings, known_findings). Each finding must have 'cid'.
        """
        new_items: list[dict] = []
        known_items: list[dict] = []
        for f in findings:
            cid = f.get("cid")
            if not cid:
                continue
            is_new = self.record(cid, f, source=f.get("source", source))
            f["is_new"] = is_new
            (new_items if is_new else known_items).append(f)
        return new_items, known_items

    def stats(self) -> dict:
        by_src: dict[str, int] = {}
        for v in self._idx.values():
            s = v.get("source", "?")
            by_src[s] = by_src.get(s, 0) + 1
        return {
            "market": self.market,
            "total_known": len(self._idx),
            "by_source": by_src,
            "log_path": self._log_path,
        }

    def new_since(self, since_iso: str) -> list[dict]:
        """Return all items first seen after since_iso (ISO timestamp string)."""
        return [
            v for v in self._idx.values()
            if v.get("first_seen_at", "") >= since_iso
        ]

    # ── Private ───────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if os.path.exists(self._mem_path):
            try:
                with open(self._mem_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning(f"[ScoutMemory] Failed to load memory index from {self._mem_path}: {exc}")
        return {}

    def _save(self):
        with open(self._mem_path, "w", encoding="utf-8") as f:
            json.dump(self._idx, f, indent=2, default=str)

    def _log_new(self, cid: str, data: dict, source: str, ts: str):
        entry = {
            "cid": cid,
            "source": source,
            "market": self.market,
            "discovered_at": ts,
            "data": {k: v for k, v in data.items() if k != "raw_snippet"},
        }
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    @staticmethod
    def _data_hash(data: dict) -> str:
        safe = {k: v for k, v in data.items()
                if k not in ("scraped_at", "cid", "is_new", "raw_snippet")}
        return hashlib.md5(
            json.dumps(safe, sort_keys=True, default=str).encode()
        ).hexdigest()

    @staticmethod
    def _label(data: dict) -> str:
        return (
            data.get("project_name") or data.get("title") or
            data.get("headline") or data.get("source_url") or ""
        )[:80]
