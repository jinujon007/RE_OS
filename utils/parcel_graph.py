"""
ParcelGraph — Form 17 Village-Depth Parcel Graph (GATE-155)

Connects survey numbers by shared buyer (land aggregation signal) and
numerical adjacency (contiguous parcels). Returns a graph structure
with edges weighted by transaction recency.
"""

import re
from collections import defaultdict
from itertools import combinations
from loguru import logger
from sqlalchemy import text as _sa_text

from utils.db import get_engine

__all__ = ["ParcelGraph"]

_SURVEY_DIGIT = re.compile(r"\d+")

# Weight floor for adjacency-only edges (no shared buyer).
# Non-zero so adjacency edges contribute to hotspot_score but remain
# lower than any shared-buyer edge (min shared-buyer weight = 0.5 for same-day tx).
_ADJACENCY_EDGE_WEIGHT = 0.1


def _normalize_buyer(name: str | None) -> str:
    if not name:
        return ""
    return " ".join(name.strip().lower().split())


def _extract_digits(survey_no: str | None) -> int | None:
    if not survey_no:
        return None
    m = _SURVEY_DIGIT.search(survey_no)
    if m:
        return int(m.group())
    return None


def _resolve_market_to_villages(engine, market: str) -> list[str]:
    """Resolve market name to village list via v_deed_village_priority.
    Returns empty list on any failure (view not yet created, no data, etc.)."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT DISTINCT village
                    FROM v_deed_village_priority
                    WHERE market ILIKE :m
                    ORDER BY village
                """),
                {"m": f"%{market}%"},
            ).fetchall()
            return [str(r[0]) for r in rows if r[0]]
    except Exception:
        logger.debug("[ParcelGraph] village resolution failed for market=%s — falling back to hobli filter", market)
        return []


def _compute_edge_weight(days: int | None, shared_buyer: bool) -> float:
    """Edge weight formula.
    For shared buyer: weight = 1/(1+days) — ranges from 1.0 (same-day) → ~0.5 at 1 day → near 0 at high days.
    For adjacency only: fixed floor weight.
    None days (missing reg_date) treated as least recent (weight = floor).
    """
    if not shared_buyer:
        return _ADJACENCY_EDGE_WEIGHT
    if days is None:
        return _ADJACENCY_EDGE_WEIGHT
    return 1.0 / (1.0 + days)


class ParcelGraph:
    """Parcel aggregation graph for a (market, village) pair.

    Designed for repeated use — instantiate once, call build() per village.
    Engine is fetched once from the global pool on first call.
    """

    def __init__(self, engine=None):
        self._engine = engine or get_engine()

    def build(self, market: str, village: str) -> dict:
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    _sa_text("""
                        SELECT survey_no, buyer_name_raw, reg_date
                        FROM registered_transactions
                        WHERE village ILIKE :village
                          AND survey_no IS NOT NULL
                          AND survey_no != ''
                          AND buyer_name_raw IS NOT NULL
                          AND buyer_name_raw != ''
                        ORDER BY reg_date
                    """),
                    {"village": f"%{village}%"},
                ).fetchall()
        except Exception:
            logger.warning("[ParcelGraph] DB query failed for market=%s village=%s", market, village)
            return {"market": market, "village": village, "nodes": [], "edges": [], "hotspot_score": 0.0}

        if not rows:
            return {"market": market, "village": village, "nodes": [], "edges": [], "hotspot_score": 0.0}

        buyer_groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            norm = _normalize_buyer(r.buyer_name_raw)
            if not norm:
                continue
            sn = r.survey_no if r.survey_no else None
            if not sn:
                continue
            buyer_groups[norm].append({
                "survey_no": sn,
                "digits": _extract_digits(sn),
                "reg_date": r.reg_date,
            })

        all_nodes: set[str] = set()
        edge_map: dict[tuple[str, str], dict] = {}

        def _add_edge(a: str, b: str, shared: bool, days: int | None = None):
            key = tuple(sorted((a, b)))
            if key in edge_map:
                edge_map[key]["transaction_count"] += 1
                if shared:
                    edge_map[key]["shared_buyer"] = True
                new_weight = _compute_edge_weight(days, shared)
                edge_map[key]["edge_weight"] = max(edge_map[key]["edge_weight"], new_weight)
            else:
                edge_map[key] = {
                    "survey_a": key[0],
                    "survey_b": key[1],
                    "shared_buyer": shared,
                    "transaction_count": 1,
                    "edge_weight": _compute_edge_weight(days, shared),
                }

        for buyer, txs in buyer_groups.items():
            all_nodes.update(t["survey_no"] for t in txs)
            for a, b in combinations(txs, 2):
                da = a["reg_date"]
                db = b["reg_date"]
                if da is not None and db is not None:
                    days = abs((da - db).days)
                else:
                    days = None
                _add_edge(a["survey_no"], b["survey_no"], True, days)

        sn_digit_map: dict[int, str] = {}
        for sn in all_nodes:
            d = _extract_digits(sn)
            if d is not None:
                if d in sn_digit_map and sn_digit_map[d] != sn:
                    logger.debug("[ParcelGraph] digit collision: %d → %s and %s", d, sn_digit_map[d], sn)
                sn_digit_map.setdefault(d, sn)

        digit_list = sorted(sn_digit_map.keys())
        for i in range(len(digit_list) - 1):
            d1, d2 = digit_list[i], digit_list[i + 1]
            if abs(d1 - d2) <= 2:
                sn1 = sn_digit_map[d1]
                sn2 = sn_digit_map[d2]
                if sn1 != sn2:
                    _add_edge(sn1, sn2, False)

        nodes = sorted(all_nodes)
        edges = list(edge_map.values())
        hotspot_score = len(edges) / max(len(nodes), 1)

        return {
            "market": market,
            "village": village,
            "nodes": nodes,
            "edges": edges,
            "hotspot_score": hotspot_score,
        }
