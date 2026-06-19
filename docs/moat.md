# RE_OS — Competitive Moat Analysis
**Last updated: 2026-06-19**

## What We Have

| Layer | What RE_OS Captures | Competitor Equivalents |
|-------|-------------------|----------------------|
| **Deed data** | Registered sale deed transactions at village depth via Form17 Index II + EC Form 15 (since 2026-06-12) | Zapkey (area aggregates), CRE Matrix (built assets only), Propstack (raw deed lookup) |
| **Pre-RERA parcel graph** | Individual survey numbers linked across deeds, RERA filings, guidance values | None — competitors work at locality/ward level |
| **Assembly detection** | Same buyer acquiring 2+ parcels in same village within 180 days (since 2026-06-12) | None — no competitor surfaces this signal |
| **Corridor scoring accuracy** | Weekly backtest since 2026-06-16 with rank correlation tracked per corridor | None — no competitor publishes corridor accuracy scores |
| **Leading indicators** | eProcurement tenders, gazette LA notifications, DC conversions, GCC hiring snapshots (since 2026-06-13) | None — no competitor fuses these signals |
| **Prediction ledger** | Every forecast logged with check date, hit-rate publicly tracked (since 2026-06-12) | None |

## What Competitors Have

| Competitor | Deed Lookup | Time-Series | Assembly Detection | Corridor Backtest | Pre-RERA Parcels |
|---|---|---|---|---|---|
| Zapkey | ✅ Area aggregates | ❌ | ❌ | ❌ | ❌ |
| CRE Matrix | ✅ Built assets | ❌ | ❌ | ❌ | ❌ |
| Propstack | ✅ Raw deeds | ❌ | ❌ | ❌ | ❌ |
| RE_OS | ✅ + Form17 village depth | ✅ Weekly since 2026-06-16 | ✅ Since 2026-06-12 | ✅ Since 2026-06-16 | ✅ Index II |

**Note:** Competitor comparison is based on public product documentation and J-14 teardown (2026-06-12). All three have deed lookup for urban Bengaluru at locality level. None have land-stage, pre-RERA, or village-depth parcel intelligence.

## Where the Gap Is

The moat is not the deed data. It is:

1. **Assembly detection**: no competitor product surfaces this signal
2. **Corridor scoring accuracy time-series**: weekly backtest since 2026-06-16 = irreplaceable if maintained for 18+ consecutive months
3. **Pre-RERA Form17 parcel graph at village depth**: not ward-level aggregates — individual survey numbers
4. **Falsifiable prediction ledger**: every claim publicly tracked, hit-rate exposed regardless of outcome

## What Closes It

18 months of uninterrupted weekly deed pipeline (by ~2027-12) = a time-series no competitor can buy or replicate quickly.
First signal of erosion: any competitor launching "corridor accuracy" scoring with historical backtest.

## Kill Criteria

| Criterion | Threshold | Review Trigger |
|-----------|-----------|----------------|
| Assembly detection throughput | < 2 real signals/month after 6 months of live operation | Review scoring sensitivity + corridor thresholds |
| Deed pipeline interruption | > 4 weeks of zero deed ingestion | Blocked by Kaveri portal change or legal action |
| Corridor accuracy | rank_correlation < 0.4 for 3 consecutive months | Review corridor scoring model entirely |

**Rationale:** The kill criteria are asymmetric — assembly detection is the highest-value wedge (competitors can't replicate without village-depth deed history), so it gets the strictest threshold. Corridor accuracy has higher tolerance (3 months) because short-term rank volatility is expected in thin deed months.

