"""
RE_OS — Agent Memory
──────────────────────
Read, write, and decay structured facts in the agent_memories PostgreSQL table.
Table is created by Alembic baseline migration (0001_initial.py).

Usage:
    from utils.agent_memory import read_memories, write_memory, decay_memories

    # Before Stage 3 crew kickoff:
    facts = read_memories("ceo", "Yelahanka", limit=5)

    # After CEO synthesis:
    write_memory("ceo", "Yelahanka", "Avg PSF ₹6,200 — 18% above GV", confidence=0.6)

    # Scheduled decay (run weekly):
    decay_memories(days=30, decay_amount=0.1)
"""

from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import create_engine, text

from config.settings import DATABASE_URL

# Single engine — shared across all calls in this process
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=2)
    return _engine


def read_memories(agent_id: str, market: str, limit: int = 5) -> list[dict]:
    """Return top-N highest-confidence facts for this agent+market.

    Returns empty list if table is empty or DB unreachable — never raises.
    """
    try:
        with _get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                SELECT fact, confidence, created_at
                FROM agent_memories
                WHERE agent_id = :agent_id
                  AND market ILIKE :market
                  AND confidence >= 0.4
                ORDER BY confidence DESC, created_at DESC
                LIMIT :limit
                """),
                {"agent_id": agent_id, "market": f"%{market}%", "limit": limit},
            ).fetchall()
            return [{"fact": r[0], "confidence": r[1], "created_at": str(r[2])} for r in rows]
    except Exception as exc:
        logger.warning(f"agent_memory.read_memories failed ({agent_id}/{market}): {exc}")
        return []


_MEMORY_ROW_CAP = 500


def write_memory(agent_id: str, market: str, fact: str, confidence: float = 0.6) -> bool:
    """Insert a new memory fact. Confidence starts at 0.6 per spec (T-244).

    If the exact same fact already exists for this agent+market, update confidence
    instead of inserting a duplicate (upsert on fact text).
    After insert, enforces a row cap of 500 per agent+market — drops lowest-confidence
    rows beyond 500 (T-297).
    Returns True on success, False on DB error.
    """
    if not fact or not fact.strip():
        return False
    confidence = max(0.0, min(1.0, confidence))  # clamp to [0, 1]
    try:
        with _get_engine().begin() as conn:
            conn.execute(
                text("""
                INSERT INTO agent_memories (agent_id, market, fact, confidence, created_at)
                VALUES (:agent_id, :market, :fact, :confidence, NOW())
                ON CONFLICT (agent_id, market, fact)
                DO UPDATE SET
                    confidence = LEAST(1.0, agent_memories.confidence + 0.05),
                    created_at = NOW()
                """),
                {
                    "agent_id": agent_id,
                    "market": market,
                    "fact": fact.strip(),
                    "confidence": confidence,
                },
            )

            # T-297: cap rows at 500 per agent+market — delete lowest-confidence excess
            count_row = conn.execute(
                text("""
                SELECT COUNT(*) FROM agent_memories
                WHERE agent_id = :agent_id AND market = :market
                """),
                {"agent_id": agent_id, "market": market},
            ).fetchone()
            row_count = count_row[0] if count_row else 0
            excess = row_count - _MEMORY_ROW_CAP
            if excess > 0:
                conn.execute(
                    text("""
                    DELETE FROM agent_memories WHERE memory_id IN (
                        SELECT memory_id FROM agent_memories
                        WHERE agent_id = :agent_id AND market = :market
                        ORDER BY confidence ASC, created_at ASC
                        LIMIT :excess
                    )
                    """),
                    {"agent_id": agent_id, "market": market, "excess": excess},
                )
                logger.debug(
                    f"[Memory] Row cap: pruned {excess} low-confidence rows "
                    f"for {agent_id}/{market} (was {row_count}, capped at {_MEMORY_ROW_CAP})"
                )

        return True
    except Exception as exc:
        logger.warning(f"agent_memory.write_memory failed ({agent_id}/{market}): {exc}")
        return False


def decay_memories(days: int = 30, decay_amount: float = 0.1) -> int:
    """Reduce confidence of facts not confirmed in the last `days` days.

    Facts that decay below 0.3 are deleted.
    Returns count of rows deleted, -1 on error.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    try:
        with _get_engine().begin() as conn:
            result = conn.execute(
                text("""
                WITH decayed AS (
                    UPDATE agent_memories
                    SET confidence = confidence - :decay
                    WHERE created_at < :cutoff
                    RETURNING memory_id, confidence
                )
                DELETE FROM agent_memories
                WHERE memory_id IN (
                    SELECT memory_id FROM decayed WHERE confidence < 0.3
                )
                """),
                {"decay": decay_amount, "cutoff": cutoff},
            )
            return result.rowcount
    except Exception as exc:
        logger.warning(f"agent_memory.decay_memories failed: {exc}")
        return -1


def detect_conflicts(market: str) -> list[dict]:
    """Detect conflicting facts in agent_memories for a market.
    
    Finds facts that appear multiple times for the same market from different agents,
    indicating potential disagreement. For facts with numeric values that differ by >20%,
    writes a conflict record with metadata.
    
    Production-ready with input validation, error handling, and observability.
    
    Returns list of conflict dicts with keys: market, fact_prefix, agent_a, agent_b,
    value_a, value_b, pct_gap.
    """
    import re
    import json
    import time
    from loguru import logger
    
    conflicts = []
    start_time = time.time()
    
    # Input validation - prevent SQL injection
    if not market or not isinstance(market, str):
        logger.warning(f"[Memory] detect_conflicts rejected invalid market: {market!r}")
        return []
    
    # Sanitize market - allow only alphanumeric and spaces
    import re as re_module
    sanitized_market = re_module.sub(r'[^a-zA-Z0-9\s]', '', market).strip()
    if not sanitized_market:
        logger.warning("[Memory] detect_conflicts rejected sanitized market")
        return []
    
    try:
        with _get_engine().connect() as conn:
            # Query for potential conflicts - facts with same 50-char prefix
            rows = conn.execute(
                text("""
                SELECT am1.agent_id AS agent_a, am2.agent_id AS agent_b,
                       am1.fact AS fact_a, am2.fact AS fact_b,
                       am1.confidence AS conf_a, am2.confidence AS conf_b,
                       am1.market
                FROM agent_memories am1
                JOIN agent_memories am2 
                  ON am1.market = am2.market 
                 AND LEFT(am1.fact, 50) = LEFT(am2.fact, 50)
                 AND am1.agent_id < am2.agent_id
                WHERE am1.market ILIKE '%' || :market || '%'
                  AND am1.confidence >= 0.4
                  AND am2.confidence >= 0.4
                  AND COALESCE(am1.fact_type, 'fact') = 'fact'
                  AND COALESCE(am2.fact_type, 'fact') = 'fact'
                ORDER BY am1.market, LEFT(am1.fact, 50)
                """),
                {"market": sanitized_market},
            ).fetchall()
            
            for row in rows:
                agent_a, agent_b, fact_a, fact_b, conf_a, conf_b, mkt = row
                
                # Extract numeric values from facts using robust regex
                nums_a = re.findall(r'₹?[\d,]+\.?\d*', fact_a)
                nums_b = re.findall(r'₹?[\d,]+\.?\d*', fact_b)
                
                if not nums_a or not nums_b:
                    continue
                
                # Parse numeric values with error handling
                try:
                    val_a = float(nums_a[0].replace('₹', '').replace(',', ''))
                    val_b = float(nums_b[0].replace('₹', '').replace(',', ''))
                except (ValueError, IndexError):
                    continue
                
                # Skip zero values
                if val_a == 0 or val_b == 0:
                    continue
                
                pct_gap = abs(val_a - val_b) / max(val_a, val_b) * 100
                
                # Only flag if >20% difference
                if pct_gap > 20:
                    fact_prefix = fact_a[:50]
                    conflict_dict = {
                        "market": mkt,
                        "fact_prefix": fact_prefix,
                        "agent_a": agent_a,
                        "agent_b": agent_b,
                        "value_a": val_a,
                        "value_b": val_b,
                        "pct_gap": round(pct_gap, 1),
                    }
                    conflicts.append(conflict_dict)
                    
                    # Write conflict record with robust JSON handling
                    try:
                        metadata_json = json.dumps({
                            "source_a": agent_a,
                            "value_a": val_a,
                            "source_b": agent_b,
                            "value_b": val_b,
                            "pct_gap": round(pct_gap, 1),
                        })
                    except (TypeError, ValueError) as json_exc:
                        logger.warning(f"[Memory] JSON serialization failed for conflict: {json_exc}")
                        metadata_json = "{}"
                    
                    conflict_fact = f"CONFLICT: {fact_prefix} — {agent_a}:₹{val_a:,.0f} vs {agent_b}:₹{val_b:,.0f} ({pct_gap:.0f}% gap)"
                    
                    try:
                        with _get_engine().begin() as write_conn:
                            write_conn.execute(
                                text("""
                                INSERT INTO agent_memories 
                                    (agent_id, market, fact, confidence, fact_type, metadata, created_at)
                                VALUES (:agent_id, :market, :fact, 0.0, 'conflict', :metadata::jsonb, NOW())
                                ON CONFLICT (agent_id, market, fact) 
                                DO UPDATE SET 
                                    confidence = 0.0,
                                    metadata = EXCLUDED.metadata,
                                    created_at = NOW()
                                """),
                                {
                                    "agent_id": "_memory_system_",
                                    "market": mkt,
                                    "fact": conflict_fact[:500],
                                    "metadata": metadata_json,
                                },
                            )
                    except Exception as write_exc:
                        logger.warning(f"[Memory] Failed to write conflict record: {write_exc}")
        
        duration_ms = (time.time() - start_time) * 1000
        logger.info(f"[Memory] detect_conflicts({sanitized_market}): {len(conflicts)} conflicts in {duration_ms:.1f}ms")
        return conflicts
        
    except Exception as exc:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(f"[Memory] detect_conflicts failed for {sanitized_market} after {duration_ms:.1f}ms: {exc}")
        return []
