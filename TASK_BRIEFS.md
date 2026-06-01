# RE_OS — Task Briefs
**Stage 3 · 2026-06-01 | Sprints 27–31**

This file is the single execution reference for both brains. Each brief gives complete context to perform the task with minimum back-and-forth. Read only the section for your assigned task — the rest is noise.

---

# T-422 — Container rebuild + Scrapling live verification

**Priority:** P0 | **Phase:** Scout Resilience | **Blocks:** Sprint 29 start

## Why

Claude Code added `scrapling[fetchers]>=0.4.0` to `requirements.txt` and wired it into `portal_scout.py` and `developer_scout.py` (T-420/T-421). The running `re_os_agents` container does not yet have Scrapling installed. This task makes it live and verifies the fetch layer is working correctly inside Docker.

Do this task before starting any Sprint 29 work.

## Context

- Scrapling uses `Fetcher` (HTTP, TLS fingerprint spoof) for bot-protected portals: `99acres_sale`, `99acres_rent`, `magicbricks`, `proptiger`, `squareyards`
- Scrapling uses `DynamicFetcher` (stealth Playwright) for JS SPAs: `housing_sale`, `nobroker`
- Both fetchers have a `_SCRAPLING_OK` guard — if import fails, existing requests/Playwright path runs unchanged
- `DynamicFetcher` reuses the Playwright Chromium already at `/ms-playwright` — no extra browser download
- The HTML attribute on a Scrapling page object is accessed via `getattr(page, "html", None) or str(page)` — **Step 3 below confirms the right attribute name and fixes it if wrong**

## Steps

**Step 1 — Rebuild and restart agents container**
```bash
docker compose build agents
docker compose up -d agents
docker compose ps
```
Confirm `re_os_agents` shows `Up` and healthy.

**Step 2 — Confirm Scrapling is installed**
```bash
docker compose exec agents python -c "
from scrapling.fetchers import Fetcher, DynamicFetcher
print('Scrapling import OK')
print('Fetcher:', Fetcher)
print('DynamicFetcher:', DynamicFetcher)
"
```
Expected: two lines naming the classes. If ImportError → requirements install failed; check build logs.

**Step 3 — Confirm page HTML attribute name**

Run this inside the container to discover what attribute holds the raw HTML:
```bash
docker compose exec agents python -c "
from scrapling.fetchers import Fetcher
page = Fetcher.get('https://httpbin.org/html', stealthy_headers=True)
print('type:', type(page))
print('has html attr:', hasattr(page, 'html'))
print('has body attr:', hasattr(page, 'body'))
print('has text attr:', hasattr(page, 'text'))
html_val = getattr(page, 'html', None)
print('html len:', len(html_val) if html_val else 'NONE')
"
```

- If `html` attribute exists and `html_val` length > 100 → no code change needed
- If `html` is `None` or missing, check `body` or `text` attribute — whichever has content > 100 chars is the right one
- Fix in **both** `scrapers/portal_scout.py` and `scrapers/developer_scout.py`:
  - Find: `getattr(page, "html", None) or str(page)`
  - Replace with: `getattr(page, "<correct_attr>", None) or str(page)`
  - There are 2 occurrences in portal_scout (one per method) and 2 in developer_scout — fix all 4

**Step 4 — Smoke test portal_scout with one Scrapling HTTP source**
```bash
docker compose exec agents python scrapers/portal_scout.py --market Yelahanka --source 99acres_sale
```

Read the log output. Look for one of these patterns:

✅ **Scrapling working:** Line contains `[Scrapling HTTP][99acres_sale]` with a char count
```
[PortalScout][Scrapling HTTP][99acres_sale] 28543 chars
```
A char count > 5000 means real HTML — Scrapling bypassed bot detection.

⚠️ **Scrapling silently falling back:** No `[Scrapling HTTP]` line, but scout completes without error. Scrapling fetched a bot-wall page (< 500 chars), fell back to requests. That's fine — fallback is working correctly. Log the char count from Step 3 to diagnose later.

❌ **Error:** Any unhandled exception in `_scrapling_http_fetch`. Capture the traceback and fix.

**Step 5 — Smoke test DynamicFetcher source**
```bash
docker compose exec agents python scrapers/portal_scout.py --market Yelahanka --source housing_sale
```
Look for `[Scrapling Dynamic][housing_sale]` in output. Same pass/fallback criteria as Step 4.

**Step 6 — Run full tests**
```bash
docker compose exec agents pytest tests/ -q -m unit
```
All existing tests must pass. No new tests required for this task — it is infrastructure verification only.

## Done When

- `docker compose ps` shows `re_os_agents` Up
- Step 2 import succeeds without error
- Step 3 HTML attribute confirmed (and code fixed if needed)
- Step 4 + Step 5 complete without unhandled exception
- Existing unit tests pass
- CHANGELOG prepended
- T-422 marked DONE in TASK_QUEUE.md

## If Scrapling DynamicFetcher Fails with Browser Error

If Step 5 raises a Playwright browser-not-found error:
```bash
docker compose exec agents python -c "
import os
print('PLAYWRIGHT_BROWSERS_PATH:', os.environ.get('PLAYWRIGHT_BROWSERS_PATH'))
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=['--no-sandbox'])
    print('Chromium OK:', b.version)
    b.close()
"
```
If Playwright's own Chromium works but DynamicFetcher doesn't, run inside the container:
```bash
scrapling install
```
Then re-test Step 5.

---

# Sprint 29 Briefs — Intelligence Layer

---

# T-390 — Alembic 0010: sentiment columns on news_articles

**Priority:** P1 | **Phase:** 8.5 | **Blocks:** T-392, T-394

## Why

The scheduler's `run_news_sentiment_scoring()` already exists and runs nightly — it writes `sentiment_score` to `news_articles`. Without the column the job silently crashes every night. This is a one-migration fix.

## Steps

1. Add to `database/schema.sql` (after news_articles table definition, before the next table):
```sql
-- Sentiment enrichment columns (added Phase 8.5 — Alembic 0010)
-- ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS sentiment_score FLOAT;
-- ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS sentiment_label VARCHAR(20);
```
Note: comment form only — Alembic manages live adds.

2. Create `alembic/versions/0010_add_sentiment_columns.py`:
```python
"""Add sentiment_score + sentiment_label to news_articles (Phase 8.5).
Revision ID: 0010_add_sentiment_columns
Revises: 0009_add_alerts_table
Create Date: 2026-05-30
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0010_add_sentiment_columns"
down_revision: Union[str, None] = "0009_add_alerts_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("news_articles", sa.Column("sentiment_score", sa.Float(), nullable=True))
    op.add_column("news_articles", sa.Column("sentiment_label", sa.String(20), nullable=True))

def downgrade() -> None:
    op.drop_column("news_articles", "sentiment_label")
    op.drop_column("news_articles", "sentiment_score")
```

## Done When
- Alembic 0010 with correct down_revision
- `py_compile` + `ruff check .` passes
- CHANGELOG prepended

---

# T-391 — settings.py + .env.example: HF_API_KEY + CHROMA_DB_PATH

**Priority:** P1 | **Phase:** 8.5 | **Blocks:** T-392, T-393

## Steps

1. In `config/settings.py`, add:
```python
# ── Intelligence Layer (Phase 8.5) ───────────────────────────────────────────
HF_API_KEY    = os.environ.get("HF_API_KEY", "")
CHROMA_DB_PATH = os.environ.get("CHROMA_DB_PATH", "/app/data/chroma")
```

2. In `.env.example`, add:
```bash
# ── Intelligence Layer ──
# HF API key for FinBERT sentiment scoring (free at huggingface.co/settings/tokens)
HF_API_KEY=
# ChromaDB persistent storage path (inside Docker — maps to a volume)
CHROMA_DB_PATH=/app/data/chroma
```

3. In `docker-compose.yml` agents + scheduler env blocks, add:
```yaml
HF_API_KEY: ${HF_API_KEY:-}
CHROMA_DB_PATH: /app/data/chroma
```

4. In `docker-compose.yml` agents + scheduler volumes, add:
```yaml
- chroma_data:/app/data/chroma
```
And at the bottom volumes section:
```yaml
chroma_data:
```

## Done When
- `settings.py` has HF_API_KEY + CHROMA_DB_PATH
- `.env.example` updated
- `docker-compose.yml` has both env vars + shared `chroma_data` volume on agents + scheduler
- `ruff check .` passes
- CHANGELOG prepended

---

# T-392 — utils/sentiment.py

**Priority:** P1 | **Phase:** 8.5 | **Depends on:** T-391

## Why

FinBERT is the standard financial sentiment model. We call HF's hosted Inference API — no local model, no GPU, no transformers dependency. If the key isn't set or the API fails, we return None and the scheduler logs a warning. Never crashes the pipeline.

## Steps

Create `utils/sentiment.py`:

```python
"""
RE_OS — Sentiment Scorer (Phase 8.5 — Intelligence Layer)
Uses HF Inference API (ProsusAI/finbert) to score news headlines as positive/negative/neutral.
Returns a float in [-1, +1]: +1 = strongly bullish, -1 = strongly bearish, 0 = neutral.
Gracefully returns None if HF_API_KEY is unset or the API fails.
"""
import json
import os
import urllib.request
import urllib.error
from loguru import logger

_FINBERT_URL = "https://api-inference.huggingface.co/models/ProsusAI/finbert"

_LABEL_MAP = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral":   0.0,
}


def score_headline(text: str) -> float | None:
    """Score a news headline using FinBERT via HF Inference API.
    Returns float in [-1, +1] or None on failure/skip."""
    api_key = (os.environ.get("HF_API_KEY") or "").strip()
    if not api_key:
        logger.debug("[Sentiment] HF_API_KEY not set — skipping sentiment scoring")
        return None

    text = (text or "").strip()
    if not text:
        return None

    payload = json.dumps({"inputs": text[:512]}).encode("utf-8")
    req = urllib.request.Request(
        _FINBERT_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
    except Exception as exc:
        logger.warning(f"[Sentiment] HF API error: {exc}")
        return None

    # HF returns [[{label, score}, ...]] — pick highest-confidence label
    try:
        candidates = result[0] if isinstance(result, list) else result
        if isinstance(candidates, list) and candidates:
            best = max(candidates, key=lambda x: x.get("score", 0))
            label = best.get("label", "neutral").lower()
            score = float(best.get("score", 0.0))
            sentiment_float = _LABEL_MAP.get(label, 0.0) * score
            return round(sentiment_float, 4)
    except Exception as exc:
        logger.warning(f"[Sentiment] Result parse error: {exc} | raw={result}")

    return None


def label_from_score(score: float | None) -> str:
    """Convert float score to human label."""
    if score is None:
        return "unscored"
    if score > 0.2:
        return "positive"
    if score < -0.2:
        return "negative"
    return "neutral"
```

## Done When
- `utils/sentiment.py` with `score_headline()` + `label_from_score()`
- Returns None when HF_API_KEY unset (no crash)
- `py_compile` + `ruff check .` passes
- CHANGELOG prepended

---

# T-393 — utils/embedder.py — IntelEmbedder

**Priority:** P1 | **Phase:** 8.5 | **Depends on:** T-391

## Why

The scheduler's `run_intel_embedding_index()` calls `IntelEmbedder().index_intel_reports(outputs_dir="/app/outputs")`. Without this class it crashes silently every night. Beyond fixing the crash, this is the foundation for semantic search over all accumulated intel — the biggest knowledge-leverage capability in Phase 8.5.

## Steps

Create `utils/embedder.py`:

```python
"""
RE_OS — Intel Embedder (Phase 8.5 — Intelligence Layer)
Indexes intel report .txt files into ChromaDB using nomic-embed-text via Ollama.
Enables semantic search: "Yelahanka PSF trend Q1 2026" → relevant excerpts.
Gracefully no-ops if Ollama unavailable or ChromaDB path unwriteable.
"""
import hashlib
import json
import os
import urllib.request
from pathlib import Path
from loguru import logger

_OLLAMA_EMBED_URL = "http://ollama:11434/api/embeddings"
_EMBED_MODEL = "nomic-embed-text"
_CHUNK_SIZE = 800      # chars per chunk — fits comfortably in 8192 token context
_CHUNK_OVERLAP = 100


def _get_chroma_client():
    import chromadb
    path = os.environ.get("CHROMA_DB_PATH", "/app/data/chroma")
    os.makedirs(path, exist_ok=True)
    return chromadb.PersistentClient(path=path)


def _embed_text(text: str) -> list[float] | None:
    """Call Ollama nomic-embed-text. Returns None on failure."""
    payload = json.dumps({"model": _EMBED_MODEL, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        _OLLAMA_EMBED_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("embedding")
    except Exception as exc:
        logger.debug(f"[Embedder] Ollama embed failed: {exc}")
        return None


def _chunk_text(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + _CHUNK_SIZE
        chunks.append(text[start:end])
        start = end - _CHUNK_OVERLAP
    return [c for c in chunks if c.strip()]


class IntelEmbedder:
    def __init__(self):
        self._client = None
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            self._client = _get_chroma_client()
            self._collection = self._client.get_or_create_collection(
                name="intel_reports",
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def index_intel_reports(self, outputs_dir: str = "/app/outputs") -> dict:
        """Index all *.txt intel reports in outputs_dir.
        Returns stats: indexed, skipped, failed."""
        stats = {"indexed": 0, "skipped": 0, "failed": 0}
        try:
            collection = self._get_collection()
        except Exception as exc:
            logger.warning(f"[Embedder] ChromaDB init failed: {exc}")
            return stats

        outputs = Path(outputs_dir)
        if not outputs.exists():
            logger.debug(f"[Embedder] outputs_dir not found: {outputs_dir}")
            return stats

        for market_dir in outputs.iterdir():
            if not market_dir.is_dir():
                continue
            market = market_dir.name
            for report in sorted(market_dir.glob("intel_report_*.txt")):
                text = report.read_text(encoding="utf-8", errors="ignore")
                chunks = _chunk_text(text)
                for i, chunk in enumerate(chunks):
                    doc_id = hashlib.sha256(f"{report.name}:{i}".encode()).hexdigest()[:16]
                    # Skip if already indexed
                    existing = collection.get(ids=[doc_id])
                    if existing["ids"]:
                        stats["skipped"] += 1
                        continue
                    embedding = _embed_text(chunk)
                    if embedding is None:
                        stats["failed"] += 1
                        continue
                    collection.add(
                        ids=[doc_id],
                        embeddings=[embedding],
                        documents=[chunk],
                        metadatas=[{"market": market, "source": report.name, "chunk": i}],
                    )
                    stats["indexed"] += 1

        logger.info(f"[Embedder] index_intel_reports: {stats}")
        return stats

    def query(self, question: str, market: str | None = None, n: int = 5) -> list[dict]:
        """Semantic search over indexed intel reports.
        Returns list of {text, market, source, score} sorted by relevance."""
        try:
            collection = self._get_collection()
        except Exception as exc:
            logger.warning(f"[Embedder] ChromaDB unavailable: {exc}")
            return []

        embedding = _embed_text(question)
        if embedding is None:
            return []

        where = {"market": market} if market else None
        try:
            results = collection.query(
                query_embeddings=[embedding],
                n_results=min(n, 10),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning(f"[Embedder] query failed: {exc}")
            return []

        output = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            output.append({
                "text": doc,
                "market": meta.get("market", ""),
                "source": meta.get("source", ""),
                "score": round(1 - dist, 4),   # cosine distance → similarity
            })
        return output
```

## Done When
- `utils/embedder.py` with `IntelEmbedder` class: `index_intel_reports()` + `query()`
- Graceful failure when Ollama unavailable (returns empty stats/list)
- `py_compile` + `ruff check .` passes
- CHANGELOG prepended

---

# T-394 — tests/test_sentiment.py

**Priority:** P1 | **Phase:** 8.5 | **Depends on:** T-392

## Steps

Create `tests/test_sentiment.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
import json
pytestmark = pytest.mark.unit

from utils.sentiment import score_headline, label_from_score


class TestScoreHeadline:
    def test_returns_none_when_no_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            result = score_headline("Real estate prices surge in Bengaluru")
            assert result is None

    def test_positive_sentiment(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps([
            [{"label": "positive", "score": 0.95},
             {"label": "negative", "score": 0.03},
             {"label": "neutral", "score": 0.02}]
        ]).encode()
        with patch.dict("os.environ", {"HF_API_KEY": "test_key"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = score_headline("Property values soar in North Bengaluru")
                assert result is not None
                assert result > 0

    def test_negative_sentiment(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps([
            [{"label": "negative", "score": 0.88},
             {"label": "neutral", "score": 0.10},
             {"label": "positive", "score": 0.02}]
        ]).encode()
        with patch.dict("os.environ", {"HF_API_KEY": "test_key"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = score_headline("Real estate market crashes")
                assert result is not None
                assert result < 0

    def test_api_error_returns_none(self):
        with patch.dict("os.environ", {"HF_API_KEY": "test_key"}):
            with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
                result = score_headline("Market report")
                assert result is None

    def test_empty_text_returns_none(self):
        with patch.dict("os.environ", {"HF_API_KEY": "test_key"}):
            result = score_headline("")
            assert result is None


class TestLabelFromScore:
    def test_positive_label(self):
        assert label_from_score(0.5) == "positive"

    def test_negative_label(self):
        assert label_from_score(-0.5) == "negative"

    def test_neutral_label(self):
        assert label_from_score(0.1) == "neutral"

    def test_none_returns_unscored(self):
        assert label_from_score(None) == "unscored"
```

## Done When
- ≥6 tests, all pass
- `ruff check .` passes
- CHANGELOG prepended

---

# T-395 — tests/test_embedder.py

**Priority:** P1 | **Phase:** 8.5 | **Depends on:** T-393

## Steps

Create `tests/test_embedder.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, call
pytestmark = pytest.mark.unit


class TestIntelEmbedder:
    def _make_embedder(self):
        from utils.embedder import IntelEmbedder
        return IntelEmbedder()

    def test_index_empty_dir(self, tmp_path):
        with patch("utils.embedder._get_chroma_client") as mock_cc, \
             patch("utils.embedder._embed_text", return_value=[0.1] * 768):
            mock_coll = MagicMock()
            mock_coll.get.return_value = {"ids": []}
            mock_cc.return_value.get_or_create_collection.return_value = mock_coll
            from utils.embedder import IntelEmbedder
            e = IntelEmbedder()
            stats = e.index_intel_reports(str(tmp_path))
            assert stats["indexed"] == 0
            assert stats["failed"] == 0

    def test_index_nonexistent_dir(self):
        with patch("utils.embedder._get_chroma_client") as mock_cc:
            mock_cc.return_value.get_or_create_collection.return_value = MagicMock()
            from utils.embedder import IntelEmbedder
            e = IntelEmbedder()
            stats = e.index_intel_reports("/nonexistent/path")
            assert stats["indexed"] == 0

    def test_query_returns_empty_when_ollama_unavailable(self):
        with patch("utils.embedder._embed_text", return_value=None), \
             patch("utils.embedder._get_chroma_client") as mock_cc:
            mock_cc.return_value.get_or_create_collection.return_value = MagicMock()
            from utils.embedder import IntelEmbedder
            e = IntelEmbedder()
            result = e.query("test question")
            assert result == []

    def test_query_returns_empty_on_chroma_error(self):
        with patch("utils.embedder._embed_text", return_value=[0.1] * 768), \
             patch("utils.embedder._get_chroma_client", side_effect=Exception("chroma down")):
            from utils.embedder import IntelEmbedder
            e = IntelEmbedder()
            result = e.query("test question")
            assert result == []

    def test_chromadb_init_failure_returns_empty_stats(self):
        with patch("utils.embedder._get_chroma_client", side_effect=Exception("no chromadb")):
            from utils.embedder import IntelEmbedder
            e = IntelEmbedder()
            stats = e.index_intel_reports("/tmp")
            assert stats["indexed"] == 0
            assert stats["failed"] == 0

    def test_embed_text_returns_none_on_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("ollama down")):
            from utils.embedder import _embed_text
            result = _embed_text("test")
            assert result is None
```

## Done When
- ≥6 tests, all pass
- CHANGELOG prepended

---

# T-396 — /api/intel/search endpoint

**Priority:** P1 | **Phase:** 8.5 | **Depends on:** T-393

## Why

The semantic search panel needs a backend endpoint. This wraps `embedder.query()` and sanitises the query parameter before passing it to ChromaDB.

## Steps

In `dashboard/app.py`:

```python
@limiter.limit("20 per minute")
@app.route("/api/intel/search", methods=["GET"])
def intel_search():
    q = (request.args.get("q") or "").strip()[:200]
    market = _normalize_market(request.args.get("market", ""))
    if not q:
        return jsonify({"results": [], "query": q})
    try:
        from utils.embedder import IntelEmbedder
        embedder = IntelEmbedder()
        results = embedder.query(q, market=market if market and market != "all" else None, n=5)
        return jsonify({"results": results, "query": q, "market": market})
    except Exception as e:
        logger.warning(f"[intel_search] {e}")
        return jsonify({"results": [], "query": q, "error": "search unavailable — index not built yet"})
```

Add `/api/intel/search` to `_READ_ONLY_PATHS`.

## Done When
- `/api/intel/search?q=...` returns `{"results": [...], "query": "..."}` or graceful empty
- Rate-limited to 20/min
- `ruff check .` passes
- CHANGELOG prepended

---

# T-397 — Dashboard Intel Search panel

**Priority:** P1 | **Phase:** 8.5 | **Depends on:** T-396

## Steps

Add to `dashboard/templates/index.html` infra-section:

```html
<div class="infra-section">
  <div class="infra-title">INTEL SEARCH</div>
  <div style="display:flex;gap:4px;margin-bottom:6px;">
    <input id="intel-search-q" type="text" placeholder="e.g. Yelahanka PSF trend 2026"
      style="flex:1;background:#0f1520;border:1px solid #2a3a55;color:#c9d1d9;padding:5px 8px;font-family:'Courier New',monospace;font-size:10px;border-radius:4px;"
      onkeydown="if(event.key==='Enter')runIntelSearch()">
    <select id="intel-search-market" style="background:#0f1520;border:1px solid #2a3a55;color:#8b949e;padding:4px;font-family:'Courier New',monospace;font-size:9px;border-radius:4px;">
      <option value="">All</option>
      <option value="yelahanka">Yelahanka</option>
      <option value="devanahalli">Devanahalli</option>
      <option value="hebbal">Hebbal</option>
    </select>
    <button onclick="runIntelSearch()" style="background:#1a2235;border:1px solid #2a3a55;color:#58a6ff;padding:5px 10px;font-size:9px;cursor:pointer;border-radius:4px;">SEARCH</button>
  </div>
  <div id="intel-search-results" style="max-height:220px;overflow-y:auto;"></div>
  <div id="intel-search-status" style="color:#6b7280;font-size:8px;margin-top:4px;"></div>
</div>
```

JS:
```javascript
async function runIntelSearch() {
  const q = (document.getElementById('intel-search-q').value || '').trim();
  const market = document.getElementById('intel-search-market').value;
  const resultEl = document.getElementById('intel-search-results');
  const statusEl = document.getElementById('intel-search-status');
  if (!q) return;
  statusEl.textContent = 'Searching…';
  resultEl.innerHTML = '';
  try {
    const url = `/api/intel/search?q=${encodeURIComponent(q)}${market ? '&market='+encodeURIComponent(market) : ''}`;
    const data = await fetch(url).then(r => r.json());
    if (data.error) {
      statusEl.textContent = data.error;
      return;
    }
    if (!data.results || !data.results.length) {
      resultEl.innerHTML = '<div style="color:#484f58;font-size:8px;padding:4px;">No results — run a pipeline first to build the index.</div>';
      statusEl.textContent = '';
      return;
    }
    resultEl.innerHTML = data.results.map(r => `
      <div style="border:1px solid #1a2235;border-radius:4px;padding:6px 8px;margin-bottom:5px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
          <span style="color:#58a6ff;font-family:'Press Start 2P',cursive;font-size:6px;">${escapeHtml(r.market || '—')}</span>
          <span style="color:#484f58;font-size:7px;">${escapeHtml(r.source || '')} · ${(r.score*100).toFixed(0)}%</span>
        </div>
        <div style="font-size:8px;color:#c9d1d9;line-height:1.4;">${escapeHtml((r.text||'').slice(0,280))}${(r.text||'').length>280?'…':''}</div>
      </div>`).join('');
    statusEl.textContent = `${data.results.length} results for "${escapeHtml(q)}"`;
    markUpdated('intel-search');
  } catch (e) {
    statusEl.textContent = 'Search failed: ' + e.message;
  }
}
```

## Done When
- Intel Search panel visible in dashboard infra panel
- Enter key + button both trigger search
- Results show excerpt + market + source + relevance %
- Empty state guides user to run pipeline first
- CHANGELOG prepended

---

# T-398 — IntelSearchTool in analyst_agent.py

**Priority:** P2 | **Phase:** 8.5 | **Depends on:** T-393

## Steps

1. In `agents/analyst_agent.py`, add:

```python
class IntelSearchTool(BaseTool):
    name: str = "intel_search"
    description: str = (
        "Search past intel reports for relevant context. "
        "Input: JSON with 'query' (str — e.g. 'Yelahanka absorption trend Q1 2026'), "
        "'market' (optional — Yelahanka/Devanahalli/Hebbal). "
        "Returns top-5 excerpts from past reports with source and relevance score. "
        "Call before forming your market assessment to leverage accumulated intelligence."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON input"})
        try:
            from utils.embedder import IntelEmbedder
            q = str(params.get("query", "")).strip()
            market = params.get("market")
            if not q:
                return json.dumps({"results": [], "note": "empty query"})
            results = IntelEmbedder().query(q, market=market, n=5)
            return json.dumps({"results": results, "count": len(results)}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "results": []})
```

2. Add `IntelSearchTool()` to analyst agent tools list.
3. Update analyst backstory adjunct guidance to mention `intel_search`.

## Done When
- `IntelSearchTool` in analyst agent tools list
- `ruff check .` passes
- CHANGELOG prepended

---

# T-399 — Scheduler: register embedding + sentiment cron jobs

**Priority:** P1 | **Phase:** 8.5 | **Depends on:** T-390, T-391

## Why

`run_intel_embedding_index()` and `run_news_sentiment_scoring()` are already defined in scheduler.py but not registered with APScheduler. They silently never run. This task adds the `scheduler.add_job()` calls.

## Steps

In `config/scheduler.py` `__main__` block, add after the memory decay job:

```python
# Intel report embedding — 4:30 AM IST (after RERA runs + before snapshot)
scheduler.add_job(
    lambda: _safe_job(run_intel_embedding_index, "intel_embedding"),
    CronTrigger(hour=4, minute=30),
    id="intel_embedding",
    name="Nightly Intel Embedding Index",
    misfire_grace_time=3600,
)

# News sentiment scoring — 5:00 AM IST
scheduler.add_job(
    lambda: _safe_job(run_news_sentiment_scoring, "news_sentiment"),
    CronTrigger(hour=5, minute=0),
    id="news_sentiment",
    name="Nightly News Sentiment Scoring",
    misfire_grace_time=3600,
)
```

Update the startup log lines and `Active jobs` log accordingly.

## Done When
- Both jobs registered in APScheduler
- `py_compile config/scheduler.py` + `ruff check .` passes
- CHANGELOG prepended

---

# T-400 — GATE-15: Phase 8.5 DoD Validation

**Priority:** P0 | **Phase:** 8.5 | **Depends on:** T-390–T-399

## Steps

1. Verify Alembic migration: `docker compose exec agents alembic current` → shows `0010_add_sentiment_columns`.
2. Test embedder standalone:
```bash
docker compose exec agents python -c "
from utils.embedder import IntelEmbedder
e = IntelEmbedder()
stats = e.index_intel_reports('/app/outputs')
print('Indexed:', stats)
results = e.query('Yelahanka PSF trend', n=3)
print('Results:', len(results))
for r in results: print(' -', r['market'], r['source'][:40], r['score'])
"
```
3. Test search API: `curl "http://localhost:8050/api/intel/search?q=absorption+rate&market=yelahanka"`
4. Test sentiment (requires HF_API_KEY — if not set, verify graceful skip):
```bash
docker compose exec agents python -c "from utils.sentiment import score_headline; print(score_headline('Bengaluru real estate market grows'))"
```
5. Verify scheduler jobs registered: `docker compose logs scheduler | grep -E 'embedding|sentiment'`
6. Document results in CHANGELOG.

## Done When
- Embedder indexes ≥1 report and query returns ≥1 result
- Sentiment returns None gracefully when key unset (or valid float when key set)
- Intel Search panel in dashboard shows results
- VISION.md Phase 8.5 marked ✅ COMPLETE
- CHANGELOG prepended

---

# Sprint 30 Briefs — Phase 12: Legal Department

---

# T-401 — utils/rera_compliance_checker.py

**Priority:** P1 | **Phase:** 12

## Why

The Board Room Legal Head currently cites RERA from LLM knowledge. This module queries the live RERA data in our DB — real project counts, actual delay rates, developer track record. It makes the legal assessment factual, not narrative.

## Steps

Create `utils/rera_compliance_checker.py`:

```python
"""
RE_OS — RERA Compliance Checker (Phase 12 — Legal Department)
Queries the DB for a developer's RERA project history and compliance signals.
"""
from dataclasses import dataclass
from loguru import logger


@dataclass
class RERAComplianceResult:
    developer_name: str
    total_projects: int
    active_projects: int
    completed_projects: int
    delayed_projects: int
    avg_delay_months: float
    compliance_signal: str   # CLEAN | WATCH | RISK
    notes: list[str]


def check_developer_compliance(developer_name: str) -> RERAComplianceResult:
    """Query rera_projects + developers for this developer's track record."""
    from utils.db import get_engine
    from sqlalchemy import text

    notes = []
    try:
        with get_engine().connect() as conn:
            row = conn.execute(text("""
                SELECT
                    COUNT(r.id) AS total,
                    COUNT(CASE WHEN r.is_active THEN 1 END) AS active,
                    COUNT(CASE WHEN r.project_status = 'Completed' THEN 1 END) AS completed,
                    COUNT(CASE WHEN r.delay_months > 0 THEN 1 END) AS delayed,
                    COALESCE(ROUND(AVG(r.delay_months)::numeric, 1), 0) AS avg_delay
                FROM rera_projects r
                JOIN developers d ON d.id = r.developer_id
                WHERE d.name ILIKE :name
            """), {"name": f"%{developer_name}%"}).fetchone()
    except Exception as exc:
        logger.warning(f"[RERACompliance] DB query failed: {exc}")
        return RERAComplianceResult(
            developer_name=developer_name,
            total_projects=0, active_projects=0, completed_projects=0,
            delayed_projects=0, avg_delay_months=0.0,
            compliance_signal="UNKNOWN",
            notes=["DB query failed — manual check required"],
        )

    if not row or row[0] == 0:
        return RERAComplianceResult(
            developer_name=developer_name,
            total_projects=0, active_projects=0, completed_projects=0,
            delayed_projects=0, avg_delay_months=0.0,
            compliance_signal="UNKNOWN",
            notes=["Developer not found in RERA Karnataka DB — verify name or check RERA portal directly"],
        )

    total, active, completed, delayed, avg_delay = row

    if delayed == 0:
        signal = "CLEAN"
        notes.append(f"No delayed projects in {total} RERA-registered projects.")
    elif delayed / max(total, 1) < 0.3 and avg_delay < 6:
        signal = "WATCH"
        notes.append(f"{delayed}/{total} projects delayed, avg {avg_delay}mo — within tolerable range.")
    else:
        signal = "RISK"
        notes.append(f"{delayed}/{total} projects delayed, avg {avg_delay}mo — material delay risk.")

    if total < 3:
        notes.append("Fewer than 3 RERA projects — limited track record. Increase diligence.")

    return RERAComplianceResult(
        developer_name=developer_name,
        total_projects=int(total),
        active_projects=int(active),
        completed_projects=int(completed),
        delayed_projects=int(delayed),
        avg_delay_months=float(avg_delay),
        compliance_signal=signal,
        notes=notes,
    )
```

## Done When
- `utils/rera_compliance_checker.py` created
- Returns `UNKNOWN` gracefully when developer not found
- `py_compile` + `ruff check .` passes
- CHANGELOG prepended

---

# T-402 — utils/zone_risk_checker.py

**Priority:** P1 | **Phase:** 12

## Steps

Create `utils/zone_risk_checker.py`:

```python
"""
RE_OS — Zone Risk Checker (Phase 12 — Legal Department)
Queries regulatory_zones + overlay_constraints for a market/zone combination.
Returns FAR, setbacks, height limit, and any overlay risk flags.
"""
from dataclasses import dataclass, field


@dataclass
class ZoneRiskResult:
    market: str
    zone: str
    far: float | None
    max_height_m: float | None
    plot_coverage: float | None
    setback_front_m: float | None
    setback_side_m: float | None
    overlay_risks: list[str] = field(default_factory=list)
    risk_level: str = "UNKNOWN"   # LOW | MEDIUM | HIGH | UNKNOWN


def check_zone_risk(market: str, zone: str = "R2") -> ZoneRiskResult:
    from utils.db import get_engine
    from sqlalchemy import text

    result = ZoneRiskResult(market=market, zone=zone,
                             far=None, max_height_m=None, plot_coverage=None,
                             setback_front_m=None, setback_side_m=None)
    try:
        with get_engine().connect() as conn:
            row = conn.execute(text("""
                SELECT rz.far, rz.max_height_m, rz.plot_coverage,
                       rz.setback_front_m, rz.setback_side_m
                FROM regulatory_zones rz
                JOIN micro_markets mm ON mm.id = rz.micro_market_id
                WHERE mm.name ILIKE :market AND rz.zone_code = :zone
                LIMIT 1
            """), {"market": f"%{market}%", "zone": zone.upper()}).fetchone()

            overlays = conn.execute(text("""
                SELECT constraint_type, description
                FROM overlay_constraints oc
                JOIN micro_markets mm ON mm.id = oc.micro_market_id
                WHERE mm.name ILIKE :market
            """), {"market": f"%{market}%"}).fetchall()
    except Exception as exc:
        result.overlay_risks = [f"DB query failed: {exc}"]
        return result

    if row:
        result.far, result.max_height_m, result.plot_coverage = row[0], row[1], row[2]
        result.setback_front_m, result.setback_side_m = row[3], row[4]

    risk_flags = []
    for ov_type, ov_desc in (overlays or []):
        if ov_type in ("airport_zone", "green_belt", "lake_buffer", "heritage_zone"):
            risk_flags.append(f"{ov_type}: {ov_desc}")

    result.overlay_risks = risk_flags

    if len(risk_flags) >= 2:
        result.risk_level = "HIGH"
    elif len(risk_flags) == 1:
        result.risk_level = "MEDIUM"
    elif row:
        result.risk_level = "LOW"

    return result
```

## Done When
- `utils/zone_risk_checker.py` created
- Returns UNKNOWN gracefully when market not found in DB
- `ruff check .` passes
- CHANGELOG prepended

---

# T-403 — Add tools to Legal Head + update backstory

**Priority:** P1 | **Phase:** 12 | **Depends on:** T-401, T-402

## Steps

1. In `agents/board_room/legal_head.py`, add tool imports + wrapper classes:

```python
from crewai.tools import BaseTool
import json
from utils.rera_compliance_checker import check_developer_compliance
from utils.zone_risk_checker import check_zone_risk


class RERAComplianceTool(BaseTool):
    name: str = "rera_compliance_check"
    description: str = (
        "Check a developer's RERA Karnataka compliance record from the DB. "
        "Input: JSON with 'developer_name' (str). "
        "Returns: total projects, delayed count, avg delay months, CLEAN/WATCH/RISK signal."
    )
    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON"})
        try:
            r = check_developer_compliance(str(params.get("developer_name", "")))
            return json.dumps({
                "developer": r.developer_name,
                "total_projects": r.total_projects,
                "delayed": r.delayed_projects,
                "avg_delay_months": r.avg_delay_months,
                "signal": r.compliance_signal,
                "notes": r.notes,
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})


class ZoneRiskTool(BaseTool):
    name: str = "zone_risk_check"
    description: str = (
        "Check regulatory zone rules and overlay constraints for a market. "
        "Input: JSON with 'market' (Yelahanka/Devanahalli/Hebbal), 'zone' (R1/R2/C1, default R2). "
        "Returns: FAR, height limit, setbacks, overlay risks (airport zone, green belt, lake buffer), risk level."
    )
    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON"})
        try:
            r = check_zone_risk(str(params.get("market", "")), str(params.get("zone", "R2")))
            return json.dumps({
                "market": r.market, "zone": r.zone,
                "far": r.far, "max_height_m": r.max_height_m,
                "plot_coverage_pct": round(r.plot_coverage * 100) if r.plot_coverage else None,
                "setback_front_m": r.setback_front_m,
                "overlay_risks": r.overlay_risks,
                "risk_level": r.risk_level,
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})
```

2. Update `build_legal_head_agent()` to include tools and update backstory:
```python
tools=[RERAComplianceTool(), ZoneRiskTool()],
```
Update backstory to mention: "You call rera_compliance_check for any named developer and zone_risk_check for any named market before forming your verdict. Your response is grounded in DB data, not general knowledge."

## Done When
- Both tools added to legal_head agent
- `ruff check .` passes
- CHANGELOG prepended

---

# T-404 — agents/compliance_researcher_agent.py

**Priority:** P1 | **Phase:** 12 | **Depends on:** T-401, T-402

## Steps

Create `agents/compliance_researcher_agent.py`:

```python
"""
RE_OS — Compliance Researcher Agent (Phase 12 — Legal Department)
Standalone researcher for RERA compliance, zone risk, and encumbrance checks.
Reports to Legal Head Agent.
"""
from crewai import Agent
from config.llm_router import get_analysis_llm
from agents.board_room.legal_head import RERAComplianceTool, ZoneRiskTool


def create_compliance_researcher_agent() -> Agent:
    return Agent(
        role="Compliance Researcher — Legal Division",
        goal=(
            "Run data-grounded compliance checks: RERA developer track record, "
            "zone regulatory risk, and encumbrance status from Kaveri data. "
            "Return structured findings the Legal Head can act on."
        ),
        backstory=(
            "Detail-oriented legal researcher specialising in Karnataka real estate regulations. "
            "Pulls directly from RERA Karnataka DB and Kaveri data — never guesses. "
            "Flags every unresolved legal item with the specific Karnataka statute or regulatory body. "
            "Output is a structured checklist: item, status, authority, recommended action."
        ),
        tools=[RERAComplianceTool(), ZoneRiskTool()],
        llm=get_analysis_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


if __name__ == "__main__":
    agent = create_compliance_researcher_agent()
    print(f"Compliance Researcher created: {agent.role}")
    print(f"Tools: {[t.name for t in agent.tools]}")
```

## Done When
- `agents/compliance_researcher_agent.py` created
- `py_compile` + `ruff check .` passes
- CHANGELOG prepended

---

# T-405 — Wire Legal Head auto-context to Board Room

**Priority:** P1 | **Phase:** 12 | **Depends on:** T-401, T-402

## Why

Engineering Head gets FSI, Finance Head gets IRR — Legal Head should get RERA compliance + zone risk automatically. Same pattern. Any pitch mentioning a developer or market gets pre-computed legal context prepended.

## Steps

In `crews/board_room.py`, add `key == "legal"` block in `run_single_agent()`:

```python
if key == "legal":
    legal_context = ""
    try:
        from utils.rera_compliance_checker import check_developer_compliance
        from utils.zone_risk_checker import check_zone_risk
        # Pull RERA compliance for any developer mentioned in pitch
        dev_match = re.search(
            r"(Brigade|Prestige|Sobha|Godrej|Adarsh|Salarpuria|Shriram|Mantri|Puravankara)",
            pitch, re.I
        )
        zone_r = check_zone_risk(market, zone="R2")
        zone_txt = (
            f"Zone R2 risk: {zone_r.risk_level}"
            f"{' — overlays: ' + ', '.join(zone_r.overlay_risks) if zone_r.overlay_risks else ' — no overlay restrictions'}"
        )
        dev_txt = ""
        if dev_match:
            dev_name = dev_match.group(1)
            rera_r = check_developer_compliance(dev_name)
            dev_txt = (
                f"\n[RERA RECORD — {dev_name}] "
                f"Projects: {rera_r.total_projects} | Delayed: {rera_r.delayed_projects} "
                f"| Avg delay: {rera_r.avg_delay_months}mo | Signal: {rera_r.compliance_signal}"
            )
        legal_context = f"\n\n[AUTO LEGAL CONTEXT — {market}]\n{zone_txt}{dev_txt}\n"
    except Exception as exc:
        logger.warning("[board_room] legal auto-context failed: %s", exc)
    dept_question = legal_context + dept_question
```

## Done When
- Legal dept_question auto-prepended with zone risk + developer RERA record
- `ruff check .` + `py_compile` passes
- CHANGELOG prepended

---

# T-406 — Dashboard Legal panel + /api/legal/brief

**Priority:** P2 | **Phase:** 12 | **Depends on:** T-403

## Steps

Same pattern as Engineering and Finance panels:
1. `GET /api/legal/brief` — returns last `legal_response` from board_sessions.
2. Add to `_READ_ONLY_PATHS`.
3. Dashboard infra-section with purple accent, shows market + CLEAR/RISK/BLOCKED badge + response excerpt.

## Done When
- `/api/legal/brief` endpoint live
- Legal panel in dashboard
- `ruff check .` passes
- CHANGELOG prepended

---

# T-407 — GATE-16: Phase 12 DoD

**Priority:** P0 | **Phase:** 12 | **Depends on:** T-401–T-406

## Steps

1. Pitch: `"5-acre Devanahalli site, R2 zone, Brigade developer — should LLS proceed?"`
2. Poll until complete.
3. Verify Legal column cites:
   - Brigade's actual RERA project count from DB
   - Devanahalli R2 zone risk level (should be LOW from regulatory_zones seed)
4. Document session_id + Legal excerpt in CHANGELOG.

## Done When
- Legal Head response contains DB-sourced data (not generic prose)
- VISION.md Phase 12 status updated to ✅ COMPLETE
- CHANGELOG prepended with evidence

---

# Sprint 31 Briefs — Phase 8: Agent Hiring

---

# T-408 — agents/registry/ + _schema.yaml

**Priority:** P1 | **Phase:** 8 | **Blocks:** T-409, T-411

## Steps

1. Create `agents/registry/` directory.
2. Create `agents/registry/_schema.yaml` (schema documentation, not loaded by code):

```yaml
# RE_OS Agent Registry — spec schema
# Every file in this directory (except _schema.yaml) is an agent spec.
# Field rules:
#   id:              unique, kebab-case, used as DB primary key
#   name:            display name (string)
#   role:            CrewAI Agent role string
#   department:      bd | engineering | finance | legal | ops | process | scout | board
#   reports_to:      id of manager agent (or "ceo")
#   persona:         backstory paragraph — determines agent's voice and priorities
#   llm_tier:        heavy | analysis | light — maps to llm_router.py tiers
#   tools:           list of tool class names available in tool_registry
#                    Known tools: MarketSummaryTool, CompetitorAnalysisTool,
#                    DistressedDeveloperListTool, ReportGeneratorTool, FeasibilityTool,
#                    FSICalculatorTool, TypologyRecommenderTool, GreenCoverageTool,
#                    FeasibilityAnalystTool, IntelSearchTool, RERAComplianceTool, ZoneRiskTool
#   markets:         list — [Yelahanka, Devanahalli, Hebbal] or []
#   memory_context:  market slug injected into system prompt — "yelahanka" | "devanahalli" | ""
#   active:          true | false
#   hired_on:        YYYY-MM-DD
#   max_iter:        int (default 3)
```

## Done When
- `agents/registry/` directory exists
- `agents/registry/_schema.yaml` committed with field documentation
- CHANGELOG prepended

---

# T-409 — Alembic 0011 + schema.sql: agent_registry table

**Priority:** P1 | **Phase:** 8 | **Depends on:** T-408

## Steps

1. Add to `database/schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS agent_registry (
    id          VARCHAR(100) PRIMARY KEY,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL,
    department  VARCHAR(50),
    spec        JSONB NOT NULL,
    llm_tier    VARCHAR(20) NOT NULL DEFAULT 'analysis'
                CHECK (llm_tier IN ('heavy', 'analysis', 'light')),
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    hired_on    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

2. Create `alembic/versions/0011_add_agent_registry.py`:
```python
"""Add agent_registry table (Phase 8 — Agent Hiring).
Revision ID: 0011_add_agent_registry
Revises: 0010_add_sentiment_columns
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0011_add_agent_registry"
down_revision: Union[str, None] = "0010_add_sentiment_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "agent_registry",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("department", sa.String(50)),
        sa.Column("spec", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("llm_tier", sa.String(20), nullable=False, server_default="analysis"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("hired_on", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.CheckConstraint("llm_tier IN ('heavy','analysis','light')", name="chk_registry_llm_tier"),
    )

def downgrade() -> None:
    op.drop_table("agent_registry")
```

## Done When
- `agent_registry` table in schema.sql + Alembic 0011
- Correct `down_revision = "0010_add_sentiment_columns"`
- CHANGELOG prepended

---

# T-410 — agents/agent_factory.py

**Priority:** P1 | **Phase:** 8 | **Depends on:** T-408

## Why

This is the central registry loader — it reads YAML spec files, resolves tool names to classes, and returns a CrewAI Agent. It also syncs the registry to DB on startup. The Hiring Panel (T-413) writes YAML files; this function is what turns those files into live agents.

## Steps

Create `agents/agent_factory.py`:

```python
"""
RE_OS — Agent Factory (Phase 8 — Agent Hiring & Onboarding)
Loads agent spec YAML files from agents/registry/ and instantiates CrewAI Agents.
Syncs the registry to the agent_registry DB table on startup.
"""
import os
from pathlib import Path
from loguru import logger

_REGISTRY_DIR = Path(__file__).parent / "registry"

_TOOL_REGISTRY: dict = {}


def _get_tool_registry() -> dict:
    """Lazily build tool name → class map. Imported once."""
    global _TOOL_REGISTRY
    if _TOOL_REGISTRY:
        return _TOOL_REGISTRY
    try:
        from agents.analyst_agent import (
            MarketSummaryTool, CompetitorAnalysisTool,
            DistressedDeveloperListTool, ReportGeneratorTool,
            FeasibilityTool, FeasibilityAnalystTool, IntelSearchTool,
        )
        from agents.architect_agent import FSICalculatorTool, TypologyRecommenderTool, GreenCoverageTool
        from agents.board_room.legal_head import RERAComplianceTool, ZoneRiskTool
        _TOOL_REGISTRY = {
            "MarketSummaryTool": MarketSummaryTool,
            "CompetitorAnalysisTool": CompetitorAnalysisTool,
            "DistressedDeveloperListTool": DistressedDeveloperListTool,
            "ReportGeneratorTool": ReportGeneratorTool,
            "FeasibilityTool": FeasibilityTool,
            "FeasibilityAnalystTool": FeasibilityAnalystTool,
            "IntelSearchTool": IntelSearchTool,
            "FSICalculatorTool": FSICalculatorTool,
            "TypologyRecommenderTool": TypologyRecommenderTool,
            "GreenCoverageTool": GreenCoverageTool,
            "RERAComplianceTool": RERAComplianceTool,
            "ZoneRiskTool": ZoneRiskTool,
        }
    except Exception as exc:
        logger.warning(f"[AgentFactory] Tool registry partially loaded: {exc}")
    return _TOOL_REGISTRY


def load_spec(yaml_path: Path) -> dict:
    """Load and validate a YAML agent spec. Returns dict or raises ValueError."""
    import yaml
    with open(yaml_path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    required = ("id", "name", "role", "persona", "llm_tier")
    for field in required:
        if not spec.get(field):
            raise ValueError(f"Agent spec {yaml_path.name} missing required field: '{field}'")
    if spec["llm_tier"] not in ("heavy", "analysis", "light"):
        raise ValueError(f"Invalid llm_tier '{spec['llm_tier']}' in {yaml_path.name}")
    return spec


def build_agent_from_spec(spec: dict):
    """Instantiate a CrewAI Agent from a spec dict."""
    from crewai import Agent
    from config.llm_router import get_heavy_llm, get_analysis_llm, get_light_llm

    tier = spec.get("llm_tier", "analysis")
    llm_fn = {"heavy": get_heavy_llm, "analysis": get_analysis_llm, "light": get_light_llm}.get(tier, get_analysis_llm)
    llm = llm_fn()

    tool_registry = _get_tool_registry()
    tools = []
    for tool_name in (spec.get("tools") or []):
        tool_cls = tool_registry.get(tool_name)
        if tool_cls:
            tools.append(tool_cls())
        else:
            logger.warning(f"[AgentFactory] Unknown tool '{tool_name}' — skipped")

    return Agent(
        role=spec["role"],
        goal=spec.get("goal", spec["role"]),
        backstory=spec["persona"],
        tools=tools,
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=int(spec.get("max_iter", 3)),
    )


def scan_registry(registry_dir: Path = _REGISTRY_DIR) -> list[dict]:
    """Return list of loaded specs from registry dir (excludes _schema.yaml)."""
    specs = []
    if not registry_dir.exists():
        return specs
    for yaml_file in sorted(registry_dir.glob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        try:
            specs.append(load_spec(yaml_file))
        except Exception as exc:
            logger.warning(f"[AgentFactory] Skipping {yaml_file.name}: {exc}")
    return specs


def sync_registry_to_db(registry_dir: Path = _REGISTRY_DIR) -> int:
    """Upsert all registry YAML specs into agent_registry DB table. Returns count."""
    from utils.db import get_engine
    from sqlalchemy import text
    import json

    specs = scan_registry(registry_dir)
    if not specs:
        return 0

    synced = 0
    try:
        with get_engine().begin() as conn:
            for spec in specs:
                conn.execute(text("""
                    INSERT INTO agent_registry (id, name, role, department, spec, llm_tier, active, hired_on)
                    VALUES (:id, :name, :role, :dept, :spec::jsonb, :tier, :active, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        name=EXCLUDED.name, role=EXCLUDED.role,
                        department=EXCLUDED.department, spec=EXCLUDED.spec,
                        llm_tier=EXCLUDED.llm_tier, active=EXCLUDED.active
                """), {
                    "id": spec["id"],
                    "name": spec["name"],
                    "role": spec["role"],
                    "dept": spec.get("department"),
                    "spec": json.dumps(spec),
                    "tier": spec["llm_tier"],
                    "active": spec.get("active", True),
                })
                synced += 1
    except Exception as exc:
        logger.warning(f"[AgentFactory] DB sync failed: {exc}")

    logger.info(f"[AgentFactory] Synced {synced} agents to registry")
    return synced
```

## Done When
- `agents/agent_factory.py` with `load_spec`, `build_agent_from_spec`, `scan_registry`, `sync_registry_to_db`
- Missing tool name logs warning (not crash)
- `py_compile` + `ruff check .` passes
- CHANGELOG prepended

---

# T-411 — Built-in registry YAML files (3 market specialists)

**Priority:** P1 | **Phase:** 8 | **Depends on:** T-408

## Steps

Create `agents/registry/market_analyst_yelahanka.yaml`:
```yaml
id: market_analyst_yelahanka
name: Rajan Rao
role: Market Intelligence Analyst — Yelahanka
department: engineering
reports_to: ceo
persona: |
  Senior analyst specialising in the Yelahanka micro-market. Deep knowledge of
  North Bengaluru residential dynamics, IT-sector hiring cycles, RERA absorption
  rates in the ₹50L–₹1.5Cr band, and developer activity from Brigade, Prestige,
  and Sobha. Tracks every new launch, price movement, and RERA registration in
  this corridor. Output is always a decision-ready brief with a go/no-go signal.
llm_tier: analysis
tools:
  - MarketSummaryTool
  - CompetitorAnalysisTool
  - IntelSearchTool
markets: [Yelahanka]
memory_context: yelahanka
active: true
hired_on: "2026-05-30"
max_iter: 3
```

Create `agents/registry/market_analyst_devanahalli.yaml` (same structure, Devanahalli context, airport corridor expertise).

Create `agents/registry/market_analyst_hebbal.yaml` (same structure, Hebbal context, lakeside/urban fringe expertise).

## Done When
- 3 YAML files in `agents/registry/`
- Each has all required fields (id, name, role, persona, llm_tier)
- `scan_registry()` returns 3 specs without error
- CHANGELOG prepended

---

# T-412 — /api/registry endpoint + sync on startup

**Priority:** P1 | **Phase:** 8 | **Depends on:** T-409, T-410

## Steps

1. In `dashboard/app.py`, add:

```python
@limiter.limit("30 per minute")
@app.route("/api/registry", methods=["GET"])
def list_registry():
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, role, department, llm_tier, active, hired_on
            FROM agent_registry ORDER BY department, name
        """)
        rows = [
            {"id": r[0], "name": r[1], "role": r[2], "department": r[3],
             "llm_tier": r[4], "active": r[5],
             "hired_on": r[6].isoformat() if r[6] else None}
            for r in cur.fetchall()
        ]
        cur.close()
        return jsonify({"agents": rows})
    except Exception as e:
        exc = True
        logger.error("[list_registry] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)
```

2. Add `/api/registry` to `_READ_ONLY_PATHS`.

3. Add `POST /api/registry` (auth-gated) to hire a new agent by posting YAML content.

4. In `docker-compose.yml` agents command, add registry sync before gunicorn:
```yaml
command:
  - sh
  - -c
  - alembic upgrade head && python -c "from agents.agent_factory import sync_registry_to_db; sync_registry_to_db()" && exec gunicorn ...
```

## Done When
- `GET /api/registry` returns all registry agents
- Startup syncs YAML files to DB
- `ruff check .` passes
- CHANGELOG prepended

---

# T-413 — Dashboard Agent Hiring panel

**Priority:** P2 | **Phase:** 8 | **Depends on:** T-412

## Steps

Add to `dashboard/templates/index.html`:

```html
<div class="infra-section">
  <div class="infra-title">AGENT REGISTRY</div>
  <div id="registry-list" style="max-height:200px;overflow-y:auto;"></div>
  <div id="registry-status" style="color:#6b7280;font-size:8px;margin-top:4px;"></div>
</div>
```

JS: `pollRegistry()` fetches `/api/registry`, renders agent cards with name, dept, llm_tier, active badge. Refresh every 60s.

Active agents show green dot. Inactive agents greyed out. Department shown as colour-coded tag.

## Done When
- Registry panel shows all registered agents
- Active/inactive badges correct
- CHANGELOG prepended

---

# T-414 — tests/test_agent_factory.py

**Priority:** P1 | **Phase:** 8 | **Depends on:** T-410

## Steps

Create `tests/test_agent_factory.py`:

```python
import pytest
from pathlib import Path
pytestmark = pytest.mark.unit


def _write_spec(tmp_path: Path, content: str, name: str = "test_agent.yaml") -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


class TestLoadSpec:
    def test_valid_spec(self, tmp_path):
        from agents.agent_factory import load_spec
        p = _write_spec(tmp_path, """
id: test_agent
name: Test Agent
role: Test Role
persona: A test persona for unit tests.
llm_tier: analysis
""")
        spec = load_spec(p)
        assert spec["id"] == "test_agent"
        assert spec["llm_tier"] == "analysis"

    def test_missing_required_field_raises(self, tmp_path):
        from agents.agent_factory import load_spec
        p = _write_spec(tmp_path, "id: test\nname: Test\n")  # missing role, persona, llm_tier
        with pytest.raises(ValueError, match="missing required field"):
            load_spec(p)

    def test_invalid_llm_tier_raises(self, tmp_path):
        from agents.agent_factory import load_spec
        p = _write_spec(tmp_path, """
id: t\nname: T\nrole: R\npersona: P\nllm_tier: superfast
""")
        with pytest.raises(ValueError, match="llm_tier"):
            load_spec(p)


class TestScanRegistry:
    def test_empty_dir(self, tmp_path):
        from agents.agent_factory import scan_registry
        result = scan_registry(tmp_path)
        assert result == []

    def test_skips_schema_file(self, tmp_path):
        from agents.agent_factory import scan_registry
        _write_spec(tmp_path, "skip: true", "_schema.yaml")
        result = scan_registry(tmp_path)
        assert result == []

    def test_loads_valid_spec(self, tmp_path):
        from agents.agent_factory import scan_registry
        _write_spec(tmp_path, """
id: x\nname: X\nrole: R\npersona: P\nllm_tier: light
""")
        result = scan_registry(tmp_path)
        assert len(result) == 1
        assert result[0]["id"] == "x"

    def test_skips_invalid_spec_logs_warning(self, tmp_path):
        from agents.agent_factory import scan_registry
        _write_spec(tmp_path, "id: bad\n")  # missing fields
        result = scan_registry(tmp_path)
        assert result == []  # bad spec skipped, no crash

    def test_nonexistent_dir_returns_empty(self):
        from agents.agent_factory import scan_registry
        result = scan_registry(Path("/nonexistent/registry"))
        assert result == []
```

## Done When
- ≥8 tests, all pass
- CHANGELOG prepended

---

# T-415 — GATE-17: Phase 8 DoD

**Priority:** P0 | **Phase:** 8 | **Depends on:** T-408–T-414

## Steps

1. Verify sync on startup: `docker compose restart agents && docker compose logs agents | grep AgentFactory`
   — should show "Synced 3 agents to registry".
2. `GET /api/registry` → returns 3 market analysts.
3. Dashboard Agent Registry panel shows 3 agents.
4. Manually hire a 4th agent (Hebbal Senior Specialist):
   - POST to `/api/registry` with a new spec (or manually create YAML + restart)
   - Verify new agent appears in `/api/registry` response
5. Document in CHANGELOG.

## Done When
- 3 built-in agents visible in `/api/registry`
- Hiring a new agent (via restart after YAML add) reflects immediately
- VISION.md Phase 8 updated to ✅ COMPLETE
- CHANGELOG prepended

---

# Sprint 27 + 28 Briefs (archived)

---

# T-366 — utils/green_coverage.py

**Priority:** P1 | **Phase:** 5 | **Blocks:** T-367, T-370

## Why

The Architect Agent currently calculates FSI and unit mix but ignores green coverage — a non-negotiable design constraint for LLS ("nature as architecture"). Green coverage is required in BDA-approved layouts (typically ≥15% of site area). This tool closes that gap with a pure-Python calculation that feeds into the architect's typology brief.

## Steps

Create `utils/green_coverage.py`:

```python
from dataclasses import dataclass

_SQFT_PER_TREE = 200  # 1 mature tree per 200 sqft of landscape area (BDA planting norm)
_MIN_GREEN_PCT_BDA = 15.0  # BDA minimum green coverage requirement (%)

@dataclass
class GreenCoverageResult:
    land_area_sqft: float
    built_coverage_pct: float     # 0.0–1.0 (from FSI result)
    landscape_area_sqft: float
    green_pct: float              # landscape as % of total land
    tree_count: int               # minimum 1
    meets_bda_minimum: bool

def calculate_green_coverage(
    land_area_sqft: float,
    built_coverage_pct: float = 0.55,
) -> GreenCoverageResult:
    land = max(land_area_sqft, 0)
    coverage = max(0.0, min(built_coverage_pct, 1.0))
    landscape = land * (1.0 - coverage)
    green_pct = (landscape / max(land, 1)) * 100
    tree_count = max(1, int(landscape / _SQFT_PER_TREE))
    return GreenCoverageResult(
        land_area_sqft=land,
        built_coverage_pct=coverage,
        landscape_area_sqft=round(landscape, 1),
        green_pct=round(green_pct, 1),
        tree_count=tree_count,
        meets_bda_minimum=green_pct >= _MIN_GREEN_PCT_BDA,
    )
```

2. `py_compile` + `ruff check .` must pass.

## Done When
- `utils/green_coverage.py` created with `GreenCoverageResult` dataclass + `calculate_green_coverage()`
- Zero land area returns landscape=0, tree_count=1 (minimum)
- built_coverage_pct clamped to [0, 1]
- `ruff check .` passes
- CHANGELOG prepended

---

# T-367 — Add GreenCoverageTool to agents/architect_agent.py

**Priority:** P1 | **Phase:** 5 | **Depends on:** T-366

## Why

The architect agent needs green coverage in every site brief it produces. Without it, every recommendation ignores the BDA minimum and LLS's own nature-first mandate.

## Steps

1. In `agents/architect_agent.py`, add after the TypologyRecommenderTool class:

```python
from utils.green_coverage import calculate_green_coverage

class GreenCoverageTool(BaseTool):
    name: str = "green_coverage"
    description: str = (
        "Calculate landscape area, tree count, and BDA green coverage compliance. "
        "Input: JSON with 'land_area_sqft' (float), 'built_coverage_pct' (0.0–1.0, "
        "use plot_coverage from fsi_calculator result). "
        "Returns landscape sqft, green %, tree count, BDA compliance flag."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON input"})
        try:
            result = calculate_green_coverage(
                land_area_sqft=float(params.get("land_area_sqft", 0)),
                built_coverage_pct=float(params.get("built_coverage_pct", 0.55)),
            )
            return json.dumps({
                "landscape_area_sqft": result.landscape_area_sqft,
                "green_pct": result.green_pct,
                "tree_count": result.tree_count,
                "meets_bda_minimum": result.meets_bda_minimum,
                "bda_minimum_pct": 15.0,
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})
```

2. Add `GreenCoverageTool()` to the `tools=[...]` list in `create_architect_agent()`.

3. Update the agent's `goal` to include: `"…green coverage compliance (BDA minimum 15%)"`.

4. `py_compile` + `ruff check .` must pass.

## Done When
- `GreenCoverageTool` class added
- Tool in `create_architect_agent()` tools list
- `ruff check .` passes
- CHANGELOG prepended

---

# T-368 — agents/renderer_agent.py

**Priority:** P1 | **Phase:** 5

## Why

Phase 5 DoD requires the Renderer Agent to produce an image prompt usable in Midjourney. This is LLS's creative engineering tool — it turns a typology brief (unit mix, location, zone) into a detailed visual prompt that the design team can feed directly into an image generator. No LLM call inside the tool — the prompt is constructed deterministically from structured inputs. The agent then enhances it with the ANALYSIS LLM.

## Steps

Create `agents/renderer_agent.py`:

```python
"""
RE_OS — Renderer Agent (Phase 5 — Engineering / Creative Division)
Given a typology brief, outputs a Midjourney/DALL-E image prompt.
"""
import json
from crewai.tools import BaseTool
from crewai import Agent
from config.llm_router import get_analysis_llm

_STYLE_PRESETS = {
    "affordable": "warm earth tones, functional landscaping, community spaces, practical amenities",
    "mid-range":  "contemporary architecture, landscaped podiums, rooftop gardens, natural light focus",
    "premium":    "luxury finishes, infinity pool, sky terraces, dense tropical greenery, dramatic lighting",
}

_LOCATION_CONTEXT = {
    "Yelahanka":    "North Bengaluru suburbs, Nandi Hills backdrop, open sky, green corridor",
    "Devanahalli":  "airport corridor, wide roads, emerging skyline, farmland contrast",
    "Hebbal":       "lakeside, Bengaluru urban fringe, elevated site with city views",
}


class ImageBriefGeneratorTool(BaseTool):
    name: str = "image_brief_generator"
    description: str = (
        "Generate a Midjourney/DALL-E image prompt from a project typology brief. "
        "Input: JSON with 'project_type' (residential/mixed), 'location' (market name), "
        "'psf_band' (affordable/mid-range/premium), 'unit_mix' (dict with 1bhk/2bhk/3bhk pct), "
        "'floors' (int), 'green_pct' (float), 'style_keywords' (optional list). "
        "Returns a prompt string ready for Midjourney v6."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON input"})
        try:
            project_type = params.get("project_type", "residential")
            location = params.get("location", "Bengaluru")
            psf_band = params.get("psf_band", "mid-range")
            unit_mix = params.get("unit_mix", {})
            floors = int(params.get("floors", 10))
            green_pct = float(params.get("green_pct", 40.0))
            extra_keywords = params.get("style_keywords", [])

            dominant_unit = max(unit_mix, key=unit_mix.get) if unit_mix else "2bhk"
            style = _STYLE_PRESETS.get(psf_band, _STYLE_PRESETS["mid-range"])
            loc_ctx = _LOCATION_CONTEXT.get(location, "Bengaluru suburban setting")
            extra = ", ".join(extra_keywords) if extra_keywords else ""

            prompt = (
                f"Architectural render of a {floors}-floor {project_type} tower in {location}, India. "
                f"{loc_ctx}. Dominant unit type: {dominant_unit.upper()}. "
                f"{round(green_pct)}% site coverage in mature tropical landscaping, podium garden. "
                f"{style}. "
                f"{''+extra+'.' if extra else ''}"
                f"Professional architectural visualization, golden hour lighting, "
                f"8k render, photorealistic, Bengaluru real estate marketing style. "
                f"--ar 16:9 --v 6"
            )
            return json.dumps({"prompt": prompt, "style_preset": psf_band, "location": location}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})


def create_renderer_agent() -> Agent:
    return Agent(
        role="Creative Renderer — Engineering Division",
        goal=(
            "Given an architectural typology brief, generate a detailed image prompt "
            "for Midjourney or DALL-E that captures the project's character, location, "
            "and product positioning."
        ),
        backstory=(
            "Visual storyteller with deep knowledge of Bengaluru residential architecture. "
            "Translates FSI math and unit mix tables into imagery that sells the lifestyle, "
            "not just the square footage. Understands how North Bengaluru's micro-climates, "
            "topography, and neighbourhood character should shape a project's visual identity. "
            "Every prompt is specific enough to produce a usable render on the first try."
        ),
        tools=[ImageBriefGeneratorTool()],
        llm=get_analysis_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=2,
    )


if __name__ == "__main__":
    tool = ImageBriefGeneratorTool()
    result = tool._run(json.dumps({
        "project_type": "residential",
        "location": "Yelahanka",
        "psf_band": "mid-range",
        "unit_mix": {"1bhk": 15, "2bhk": 55, "3bhk": 30},
        "floors": 12,
        "green_pct": 45.0,
    }))
    print(json.loads(result)["prompt"])
```

2. `py_compile` + `ruff check .` must pass.

## Done When
- `agents/renderer_agent.py` created with `ImageBriefGeneratorTool` + `create_renderer_agent()`
- `__main__` block produces a valid prompt string when run
- `ruff check .` passes
- CHANGELOG prepended

---

# T-369 — Wire Architect tools into Analyst Agent

**Priority:** P1 | **Phase:** 5 | **Depends on:** T-366, T-367

## Why

The Analyst Agent runs market analysis but has no site-level tool — it can tell you the average PSF and absorption but can't say "given this land area and zone, here's the buildable area and unit mix." Wiring FSICalculatorTool + TypologyRecommenderTool into the analyst turns it from a market reader into a site evaluator. The tools are already built; this is plumbing.

## Steps

1. In `agents/analyst_agent.py`, add imports at the top:
```python
from agents.architect_agent import FSICalculatorTool, TypologyRecommenderTool, GreenCoverageTool
```

2. In `create_analyst_agent()`, add three tools to the `tools=[...]` list:
```python
FSICalculatorTool(),
TypologyRecommenderTool(),
GreenCoverageTool(),
```

3. Update the agent `backstory` adjunct guidance section to include:
```
"ADJUNCT TOOLS — fsi_calculator / typology_recommender / green_coverage: Call only when evaluating a specific land parcel. Use avg_listing_psf from market_summary_query as input to typology_recommender. Not part of standard pipeline sequence."
```

4. `py_compile agents/analyst_agent.py` + `ruff check .` must pass.

## Done When
- Three architect tools added to analyst tool list
- Backstory adjunct guidance updated
- `ruff check .` passes
- CHANGELOG prepended

---

# T-370 — tests/test_green_coverage.py

**Priority:** P1 | **Phase:** 5 | **Depends on:** T-366

## Why

Green coverage math feeds into BDA compliance checks. If the calculation is wrong, the architect brief recommends a layout that violates regulations. Unit tests are the only guard against silent regressions.

## Steps

Create `tests/test_green_coverage.py`:

```python
import pytest
pytestmark = pytest.mark.unit

from utils.green_coverage import calculate_green_coverage, _MIN_GREEN_PCT_BDA, _SQFT_PER_TREE


class TestCalculateGreenCoverage:
    def test_standard_r2_coverage(self):
        r = calculate_green_coverage(10000, 0.55)
        assert r.landscape_area_sqft == pytest.approx(4500.0)
        assert r.green_pct == pytest.approx(45.0)

    def test_zero_land_area(self):
        r = calculate_green_coverage(0, 0.55)
        assert r.landscape_area_sqft == 0.0
        assert r.tree_count == 1  # minimum 1

    def test_full_built_coverage(self):
        r = calculate_green_coverage(10000, 1.0)
        assert r.landscape_area_sqft == 0.0
        assert r.green_pct == 0.0
        assert r.meets_bda_minimum is False

    def test_zero_built_coverage(self):
        r = calculate_green_coverage(10000, 0.0)
        assert r.landscape_area_sqft == 10000.0
        assert r.green_pct == 100.0
        assert r.meets_bda_minimum is True

    def test_bda_minimum_exactly_met(self):
        r = calculate_green_coverage(10000, 0.85)  # 15% landscape exactly
        assert r.meets_bda_minimum is True

    def test_bda_minimum_just_missed(self):
        r = calculate_green_coverage(10000, 0.86)  # 14% landscape
        assert r.meets_bda_minimum is False

    def test_tree_count_calculation(self):
        r = calculate_green_coverage(10000, 0.55)
        expected_trees = int(4500 / _SQFT_PER_TREE)
        assert r.tree_count == expected_trees

    def test_built_coverage_clamped_above_1(self):
        r = calculate_green_coverage(10000, 2.0)
        assert r.built_coverage_pct == 1.0
        assert r.landscape_area_sqft == 0.0
```

## Done When
- `tests/test_green_coverage.py` with ≥8 tests, all pass
- `pytest tests/test_green_coverage.py -q` shows 0 failures
- CHANGELOG prepended

---

# T-371 — Dashboard Engineering Panel

**Priority:** P2 | **Phase:** 5 | **Depends on:** T-367, T-368

## Why

Phase 5 DoD includes a dashboard Engineering panel. Jinu should be able to see the last FSI/typology result and image prompt without running a script. The panel pulls from the Board Room sessions table (engineering_response column) or from a direct architect run.

## Steps

1. Add to `dashboard/app.py`:

```python
@limiter.limit("30 per minute")
@app.route("/api/engineering/brief", methods=["GET"])
def engineering_brief():
    """Return the most recent Engineering Head response from board_sessions."""
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT session_id, market, engineering_response, created_at
            FROM board_sessions
            WHERE engineering_response IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        if not row:
            return jsonify({"brief": None})
        return jsonify({
            "brief": {
                "session_id": str(row[0]),
                "market": row[1],
                "response": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
            }
        })
    except Exception as e:
        exc = True
        logger.error("[engineering_brief] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)
```

2. Add `/api/engineering/brief` to `_READ_ONLY_PATHS`.

3. Add to `dashboard/templates/index.html` — new infra-section in the right panel:

```html
<div class="infra-section">
  <div class="infra-title">ENGINEERING
    <button class="db-explorer-refresh" onclick="pollEngineeringBrief()" title="Refresh">⟳</button>
  </div>
  <div id="engineering-brief-market" style="color:#58a6ff;font-family:'Press Start 2P',cursive;font-size:7px;margin-bottom:6px;"></div>
  <div id="engineering-brief-content" style="font-size:9px;color:#c9d1d9;line-height:1.5;max-height:200px;overflow-y:auto;white-space:pre-wrap;"></div>
  <div id="engineering-brief-status" style="color:#6b7280;font-size:8px;margin-top:4px;"></div>
</div>
```

4. Add JS:
```javascript
async function pollEngineeringBrief() {
  try {
    const data = await fetch('/api/engineering/brief').then(r => r.json());
    const marketEl = document.getElementById('engineering-brief-market');
    const contentEl = document.getElementById('engineering-brief-content');
    const statusEl = document.getElementById('engineering-brief-status');
    if (data.brief) {
      marketEl.textContent = data.brief.market || '';
      contentEl.textContent = (data.brief.response || '').slice(0, 800);
      statusEl.textContent = 'Session ' + (data.brief.session_id || '').slice(0, 8);
      markUpdated('engineering');
    } else {
      contentEl.textContent = 'No engineering brief yet — run a Board Room session.';
    }
  } catch (e) { /* silent */ }
}
pollEngineeringBrief();
setInterval(pollEngineeringBrief, 60000);
```

## Done When
- `/api/engineering/brief` endpoint live
- Engineering panel visible in dashboard
- `ruff check .` + `py_compile` passes
- CHANGELOG prepended

---

# T-372 — GATE-12: Phase 5 DoD Validation

**Priority:** P0 | **Phase:** 5 | **Depends on:** T-366–T-371

## Why

Phase 5 does not close until verified live. The DoD is: "Pass a land parcel to the Architect Agent, receive typology recommendation with unit mix and FSI math. Renderer Agent outputs a usable image prompt."

## Steps

1. Run Architect Agent standalone:
```bash
docker compose exec agents python agents/architect_agent.py
```
Verify output shows: buildable area, sellable area, max floors, unit mix, green coverage, BDA compliance flag.

2. Run Renderer Agent standalone:
```bash
docker compose exec agents python agents/renderer_agent.py
```
Verify output shows: a Midjourney prompt string with `--ar 16:9 --v 6` suffix.

3. Check Engineering panel at `http://localhost:8050` loads without error.

4. Document in CHANGELOG: both outputs, any issues found.

## Done When
- Both agents run without error
- Architect output contains FSI + typology + green coverage
- Renderer output contains a usable Midjourney prompt
- Engineering panel shows last Board Room engineering response
- VISION.md Phase 5 status updated to ✅ COMPLETE
- CHANGELOG prepended with evidence

---

# T-373 — utils/irr_model.py

**Priority:** P1 | **Phase:** 6 | **Blocks:** T-374, T-375

## Why

The Board Room Finance Head currently gives IRR estimates from LLM knowledge — which means made-up numbers dressed as analysis. This module replaces that with the actual LLS standard model. Every feasibility from this point forward uses the same baseline assumptions, making results comparable across pitches.

**LLS Standard Assumptions (confirmed 2026-05-30):**
- Construction cost: ₹2,200/sqft (hard cost, mid-range residential)
- Target IRR: 20% (GO threshold), 12% (MARGINAL), below 12% = NO-GO
- Standard financing: 60% equity, 40% debt
- Timeline: 18 months land acquisition → RERA registration, 36 months RERA → possession

## Steps

Create `utils/irr_model.py`:

```python
"""
RE_OS — IRR Model (Phase 6 — Finance Department)
LLS standard feasibility model. Assumptions confirmed 2026-05-30.

Standards:
  Construction cost:  ₹2,200/sqft (hard cost, mid-range residential)
  Target IRR:        ≥20% = GO | 12–20% = MARGINAL | <12% = NO-GO
  Financing:         60% equity / 40% debt
  Timeline:          18mo land→RERA + 36mo RERA→possession = 54mo total
"""
from dataclasses import dataclass
from typing import Optional

# ── LLS Standard Assumptions ─────────────────────────────────────────────────
CONSTRUCTION_COST_PSF: float = 2200.0     # ₹/sqft hard cost
TARGET_IRR_GO:         float = 20.0       # % — project green-lights above this
TARGET_IRR_MARGINAL:   float = 12.0       # % — conditional zone
EQUITY_RATIO:          float = 0.60       # 60% equity
DEBT_RATIO:            float = 0.40       # 40% debt
LAND_TO_RERA_MONTHS:   int   = 18
RERA_TO_POSSESSION_MONTHS: int = 36
TOTAL_TIMELINE_MONTHS: int   = LAND_TO_RERA_MONTHS + RERA_TO_POSSESSION_MONTHS


@dataclass
class LandCostResult:
    area_sqft: float
    guidance_value_psf: float
    negotiation_discount_pct: float
    raw_land_cost: float
    negotiated_land_cost: float

@dataclass
class GDVResult:
    sellable_area_sqft: float
    sell_psf: float
    gross_development_value: float
    monthly_revenue: float

@dataclass
class IRRResult:
    land_cost: float
    construction_cost: float
    total_project_cost: float
    gdv: float
    net_profit: float
    profit_margin_pct: float
    simple_irr_pct: float
    equity_required: float
    debt_required: float
    payback_months: int
    verdict: str   # GO | MARGINAL | NO-GO

@dataclass
class ScenarioResult:
    base: IRRResult
    bull: IRRResult
    bear: IRRResult
    recommendation: str


def calc_land_cost(
    area_sqft: float,
    guidance_value_psf: float,
    negotiation_discount_pct: float = 10.0,
) -> LandCostResult:
    area = max(area_sqft, 0)
    gv = max(guidance_value_psf, 0)
    disc = max(0.0, min(negotiation_discount_pct, 50.0))
    raw = area * gv
    negotiated = raw * (1 - disc / 100)
    return LandCostResult(
        area_sqft=area,
        guidance_value_psf=gv,
        negotiation_discount_pct=disc,
        raw_land_cost=round(raw),
        negotiated_land_cost=round(negotiated),
    )


def calc_gdv(sellable_area_sqft: float, sell_psf: float) -> GDVResult:
    area = max(sellable_area_sqft, 0)
    psf  = max(sell_psf, 0)
    gdv  = area * psf
    monthly = gdv / max(RERA_TO_POSSESSION_MONTHS, 1)
    return GDVResult(
        sellable_area_sqft=area,
        sell_psf=psf,
        gross_development_value=round(gdv),
        monthly_revenue=round(monthly),
    )


def calc_irr(
    land_cost: float,
    sellable_area_sqft: float,
    sell_psf: float,
    construction_cost_psf: float = CONSTRUCTION_COST_PSF,
    timeline_months: int = TOTAL_TIMELINE_MONTHS,
) -> IRRResult:
    lc   = max(land_cost, 0)
    area = max(sellable_area_sqft, 0)
    gdv_r = calc_gdv(area, sell_psf)
    const_cost = area * max(construction_cost_psf, 0)
    total_cost = lc + const_cost
    profit = gdv_r.gross_development_value - total_cost
    margin = (profit / max(gdv_r.gross_development_value, 1)) * 100
    years  = max(timeline_months, 1) / 12
    irr    = (profit / max(total_cost, 1)) / years * 100

    if irr >= TARGET_IRR_GO:
        verdict = "GO"
    elif irr >= TARGET_IRR_MARGINAL:
        verdict = "MARGINAL"
    else:
        verdict = "NO-GO"

    monthly_rev = gdv_r.gross_development_value / max(timeline_months, 1)
    payback = int(total_cost / max(monthly_rev, 1)) if monthly_rev > 0 else 9999

    return IRRResult(
        land_cost=round(lc),
        construction_cost=round(const_cost),
        total_project_cost=round(total_cost),
        gdv=gdv_r.gross_development_value,
        net_profit=round(profit),
        profit_margin_pct=round(margin, 1),
        simple_irr_pct=round(irr, 1),
        equity_required=round(total_cost * EQUITY_RATIO),
        debt_required=round(total_cost * DEBT_RATIO),
        payback_months=payback,
        verdict=verdict,
    )


def compare_scenarios(
    land_cost: float,
    sellable_area_sqft: float,
    base_psf: float,
) -> ScenarioResult:
    bull_psf  = base_psf * 1.10   # +10% optimistic
    bear_psf  = base_psf * 0.90   # -10% downside

    base = calc_irr(land_cost, sellable_area_sqft, base_psf)
    bull = calc_irr(land_cost, sellable_area_sqft, bull_psf)
    bear = calc_irr(land_cost, sellable_area_sqft, bear_psf)

    if base.verdict == "GO" and bear.verdict != "NO-GO":
        rec = "PROCEED — base and bear cases both viable."
    elif base.verdict == "GO" and bear.verdict == "NO-GO":
        rec = "CONDITIONAL — base GO but bear NO-GO. Negotiate land cost or add JD structure."
    elif base.verdict == "MARGINAL":
        rec = "HOLD — marginal base case. Improve land cost or increase sell PSF before committing."
    else:
        rec = "PASS — base case NO-GO. Economics do not work at current inputs."

    return ScenarioResult(base=base, bull=bull, bear=bear, recommendation=rec)
```

2. `py_compile` + `ruff check .` must pass.

## Done When
- `utils/irr_model.py` with all 4 functions + 5 dataclasses
- `ruff check .` passes
- CHANGELOG prepended

---

# T-374 — tests/test_irr_model.py

**Priority:** P1 | **Phase:** 6 | **Depends on:** T-373 | **Gates:** GATE-13 prereq

## Steps

Create `tests/test_irr_model.py`:

```python
import pytest
pytestmark = pytest.mark.unit

from utils.irr_model import (
    calc_land_cost, calc_gdv, calc_irr, compare_scenarios,
    TARGET_IRR_GO, TARGET_IRR_MARGINAL, CONSTRUCTION_COST_PSF,
    EQUITY_RATIO, DEBT_RATIO, TOTAL_TIMELINE_MONTHS,
)


class TestCalcLandCost:
    def test_basic(self):
        r = calc_land_cost(43560, 4000, 10.0)
        assert r.raw_land_cost == 43560 * 4000
        assert r.negotiated_land_cost == round(43560 * 4000 * 0.90)

    def test_zero_area(self):
        r = calc_land_cost(0, 4000)
        assert r.raw_land_cost == 0

    def test_discount_clamped_to_50(self):
        r = calc_land_cost(10000, 4000, 99.0)
        assert r.negotiation_discount_pct == 50.0

    def test_no_discount(self):
        r = calc_land_cost(10000, 4000, 0)
        assert r.negotiated_land_cost == r.raw_land_cost


class TestCalcGDV:
    def test_basic(self):
        r = calc_gdv(10000, 7000)
        assert r.gross_development_value == 70_000_000

    def test_zero_psf(self):
        r = calc_gdv(10000, 0)
        assert r.gross_development_value == 0

    def test_monthly_revenue_nonzero(self):
        r = calc_gdv(10000, 7000)
        assert r.monthly_revenue > 0


class TestCalcIRR:
    def test_go_verdict_high_psf(self):
        r = calc_irr(10_000_000, 10000, 9000)
        assert r.verdict == "GO"
        assert r.simple_irr_pct >= TARGET_IRR_GO

    def test_no_go_verdict_low_psf(self):
        r = calc_irr(50_000_000, 10000, 3000)
        assert r.verdict == "NO-GO"

    def test_equity_debt_split(self):
        r = calc_irr(20_000_000, 10000, 7000)
        assert abs(r.equity_required / r.total_project_cost - EQUITY_RATIO) < 0.01
        assert abs(r.debt_required / r.total_project_cost - DEBT_RATIO) < 0.01

    def test_zero_land_cost(self):
        r = calc_irr(0, 10000, 7000)
        assert r.land_cost == 0
        assert r.simple_irr_pct > 0

    def test_profit_margin_positive_when_go(self):
        r = calc_irr(5_000_000, 10000, 9000)
        assert r.profit_margin_pct > 0


class TestCompareScenarios:
    def test_scenario_structure(self):
        s = compare_scenarios(15_000_000, 10000, 7000)
        assert s.base is not None
        assert s.bull.gdv > s.base.gdv
        assert s.bear.gdv < s.base.gdv

    def test_bull_higher_irr_than_bear(self):
        s = compare_scenarios(15_000_000, 10000, 7000)
        assert s.bull.simple_irr_pct > s.bear.simple_irr_pct

    def test_recommendation_string_present(self):
        s = compare_scenarios(15_000_000, 10000, 7000)
        assert isinstance(s.recommendation, str)
        assert len(s.recommendation) > 0

    def test_proceed_when_base_and_bear_viable(self):
        s = compare_scenarios(5_000_000, 10000, 9000)
        assert "PROCEED" in s.recommendation

    def test_pass_when_base_no_go(self):
        s = compare_scenarios(100_000_000, 5000, 3000)
        assert "PASS" in s.recommendation
```

## Done When
- `tests/test_irr_model.py` with ≥15 tests, all pass
- CHANGELOG prepended

---

# T-375 — FeasibilityAnalystTool in agents/analyst_agent.py

**Priority:** P1 | **Phase:** 6 | **Depends on:** T-373

## Why

The Analyst Agent today can tell you market PSF and competitor data but can't run a full feasibility. This tool wires the IRR model into the analyst pipeline — so when asked to evaluate a land parcel, the analyst returns a real financial verdict, not prose.

## Steps

1. In `agents/analyst_agent.py`, add import:
```python
from utils.irr_model import calc_land_cost, calc_gdv, calc_irr, compare_scenarios
```

2. Add `FeasibilityAnalystTool` class after `FeasibilityTool`:

```python
class FeasibilityAnalystTool(BaseTool):
    name: str = "full_feasibility"
    description: str = (
        "Run a complete LLS feasibility model for a land parcel. "
        "Input: JSON with 'land_area_sqft' (float), 'sell_psf' (float — use avg_listing_psf from "
        "market_summary_query), 'guidance_value_psf' (float — from kaveri data, or use 4000 as default "
        "for Yelahanka), 'negotiation_discount_pct' (float, default 10), 'efficiency_ratio' (default 0.65), "
        "'zone' (default R2), 'market' (market name). "
        "Returns: land cost, construction cost, GDV, base/bull/bear IRR, verdict, recommendation."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON input"})
        try:
            from utils.fsi_calculator import calculate_fsi
            land_area   = float(params.get("land_area_sqft", 0))
            sell_psf    = float(params.get("sell_psf", 0))
            gv_psf      = float(params.get("guidance_value_psf", 4000))
            disc        = float(params.get("negotiation_discount_pct", 10.0))
            efficiency  = float(params.get("efficiency_ratio", 0.65))
            zone        = str(params.get("zone", "R2"))
            market      = params.get("market")

            fsi_r       = calculate_fsi(land_area, zone, efficiency, market)
            lc_r        = calc_land_cost(land_area, gv_psf, disc)
            scenarios   = compare_scenarios(lc_r.negotiated_land_cost, fsi_r.sellable_area_sqft, sell_psf)

            return json.dumps({
                "inputs": {
                    "land_area_sqft": land_area,
                    "zone": zone,
                    "market": market,
                    "sell_psf": sell_psf,
                    "guidance_value_psf": gv_psf,
                    "negotiation_discount_pct": disc,
                },
                "fsi": {
                    "buildable_sqft": fsi_r.buildable_area_sqft,
                    "sellable_sqft": fsi_r.sellable_area_sqft,
                    "max_floors": fsi_r.max_floors,
                },
                "financials": {
                    "land_cost": scenarios.base.land_cost,
                    "construction_cost": scenarios.base.construction_cost,
                    "total_project_cost": scenarios.base.total_project_cost,
                    "equity_required": scenarios.base.equity_required,
                    "gdv": scenarios.base.gdv,
                },
                "scenarios": {
                    "base":  {"irr_pct": scenarios.base.simple_irr_pct,  "verdict": scenarios.base.verdict},
                    "bull":  {"irr_pct": scenarios.bull.simple_irr_pct,  "verdict": scenarios.bull.verdict},
                    "bear":  {"irr_pct": scenarios.bear.simple_irr_pct,  "verdict": scenarios.bear.verdict},
                },
                "recommendation": scenarios.recommendation,
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})
```

3. Add `FeasibilityAnalystTool()` to the `tools=[...]` list in `create_analyst_agent()`.

4. Update analyst backstory adjunct guidance to include `full_feasibility`.

5. `py_compile` + `ruff check .` must pass.

## Done When
- `FeasibilityAnalystTool` added to analyst agent
- Tool returns base/bull/bear IRR scenarios in a single call
- `ruff check .` passes
- CHANGELOG prepended

---

# T-376 — agents/finance_head_agent.py

**Priority:** P1 | **Phase:** 6 | **Depends on:** T-373, T-375

## Why

The Finance Head in the Board Room is an inline builder function. Phase 6 creates a standalone Finance Head Agent — importable, testable, callable outside the Board Room — which makes it usable as a first-class pipeline component (not just board room context).

## Steps

Create `agents/finance_head_agent.py`:

```python
"""
RE_OS — Finance Head Agent (Phase 6 — Finance Department)
Standalone feasibility analyst for LLS land acquisition decisions.
Uses LLS standard model: ₹2,200/sqft construction, 20% IRR threshold, 60:40 equity:debt.
"""
import json
from crewai import Agent
from config.llm_router import get_analysis_llm
from agents.analyst_agent import FeasibilityAnalystTool, FeasibilityTool


def create_finance_head_agent() -> Agent:
    return Agent(
        role="VP — Finance & Capital Strategy",
        goal=(
            "Evaluate land acquisition feasibility using the LLS standard model. "
            "Produce a one-page financial verdict: land cost, GDV, base/bull/bear IRR, "
            "equity requirement, and a GO / MARGINAL / NO-GO recommendation."
        ),
        backstory=(
            "Conservative capital allocator with 12 years in Bengaluru real estate finance. "
            "Uses the LLS standard model: ₹2,200/sqft hard construction cost, 20% IRR threshold "
            "for a GO, 60:40 equity:debt. Builds three scenarios for every deal — base, bull (+10% PSF), "
            "bear (-10% PSF) — and makes the GO/NO-GO call on the bear case, not the base. "
            "Never accepts a deal where the bear case IRR falls below 12%. "
            "Always asks: what is the downside, and can LLS survive it?"
        ),
        tools=[FeasibilityAnalystTool(), FeasibilityTool()],
        llm=get_analysis_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


if __name__ == "__main__":
    agent = create_finance_head_agent()
    print(f"Finance Head Agent created: {agent.role}")
    print(f"Tools: {[t.name for t in agent.tools]}")
```

2. `py_compile` + `ruff check .` must pass.

## Done When
- `agents/finance_head_agent.py` created
- `py_compile` passes
- `ruff check .` passes
- CHANGELOG prepended

---

# T-377 — Wire Finance Head to Board Room — auto IRR math

**Priority:** P1 | **Phase:** 6 | **Depends on:** T-373

## Why

The Board Room Finance Head currently responds from LLM knowledge. This task wires the IRR model into the Finance Head's context — so any pitch that mentions a PSF or acreage gets a pre-computed base/bull/bear IRR prepended to the Finance department question. Same pattern as T-363 for Engineering.

## Steps

1. In `crews/board_room.py`, the `run_single_agent` function already handles `key == "engineering"`. Add a parallel block for `key == "finance"`:

```python
if key == "finance":
    from utils.irr_model import compare_scenarios, calc_land_cost
    irr_context = ""
    # Detect acreage
    area_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-\s*)?acres?", pitch, re.I)
    sqft_match = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:sq\s*\.?\s*ft|sqft|square\s*feet|sft)", pitch, re.I)
    # Detect PSF
    psf_match = re.search(r"(?:psf|per\s+sq\.?\s*ft|₹\s*)(\d{3,6})", pitch, re.I)
    if (area_match or sqft_match) and psf_match:
        try:
            if area_match:
                sqft = float(area_match.group(1)) * 43560
            else:
                sqft = float(sqft_match.group(1).replace(",", ""))
            sell_psf = float(psf_match.group(1))
            sellable = sqft * 0.65 * 2.5  # R2 FSI default
            scenarios = compare_scenarios(sqft * 4000 * 0.9, sellable, sell_psf)
            irr_context = (
                f"\n\n[AUTO IRR CALC — {sqft:,.0f} sqft site, ₹{sell_psf:,.0f} PSF]\n"
                f"Base IRR: {scenarios.base.simple_irr_pct:.1f}% ({scenarios.base.verdict}) | "
                f"Bull: {scenarios.bull.simple_irr_pct:.1f}% | "
                f"Bear: {scenarios.bear.simple_irr_pct:.1f}% ({scenarios.bear.verdict})\n"
                f"Land cost est.: ₹{scenarios.base.land_cost/1e7:.1f}Cr | "
                f"GDV est.: ₹{scenarios.base.gdv/1e7:.1f}Cr\n"
                f"Recommendation: {scenarios.recommendation}\n"
            )
        except Exception:
            pass
    dept_question = irr_context + dept_question
```

2. `py_compile crews/board_room.py` + `ruff check .` must pass.

## Done When
- Finance dept question auto-prepended with IRR calc when pitch contains PSF + area
- `ruff check .` passes
- CHANGELOG prepended

---

# T-378 — Dashboard Finance Panel

**Priority:** P2 | **Phase:** 6 | **Depends on:** T-376

## Why

Jinu needs to see the last feasibility calc without opening a terminal. The Finance panel in the dashboard shows the last Board Room Finance Head response alongside the key numbers.

## Steps

1. Add to `dashboard/app.py`:

```python
@limiter.limit("30 per minute")
@app.route("/api/finance/brief", methods=["GET"])
def finance_brief():
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT session_id, market, finance_response, created_at
            FROM board_sessions
            WHERE finance_response IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        if not row:
            return jsonify({"brief": None})
        return jsonify({"brief": {
            "session_id": str(row[0]),
            "market": row[1],
            "response": row[2],
            "created_at": row[3].isoformat() if row[3] else None,
        }})
    except Exception as e:
        exc = True
        logger.error("[finance_brief] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)
```

2. Add `/api/finance/brief` to `_READ_ONLY_PATHS`.

3. Add Finance panel to `index.html` (same structure as Engineering panel, purple accent colour `#9b7ec7`).

4. Add JS: `pollFinanceBrief()` called on load + 60s interval.

## Done When
- `/api/finance/brief` endpoint live
- Finance panel in dashboard showing last finance response
- `ruff check .` passes
- CHANGELOG prepended

---

# T-379 — GATE-13: Phase 6 DoD Validation

**Priority:** P0 | **Phase:** 6 | **Depends on:** T-373–T-378

## Why

Phase 6 does not close until the Finance Head demonstrably uses calculated IRR, not LLM guesses.

## Steps

1. Submit Board Room pitch: `"Should LLS acquire a 5-acre site in Yelahanka at ₹6,500 PSF via JD model?"`
2. Poll session until complete.
3. Check Finance column in the result — it must contain a number ending in `%` that matches the IRR model output for those inputs (5 acres = 217,800 sqft, 65% efficiency, R2 zone, PSF ₹6,500).
4. Expected base IRR: `calc_irr(217800 * 4000 * 0.9, 217800 * 0.65 * 2.5, 6500)` — verify output matches Finance Head response.
5. Document session_id + Finance Head excerpt in CHANGELOG.

## Done When
- Finance Head response contains calculated IRR % (not vague prose like "approximately 18-22%")
- IRR matches model output for given inputs
- VISION.md Phase 6 status updated to ✅ COMPLETE
- CHANGELOG prepended with evidence

---

# T-380 — DB: alerts table + Alembic 0009

**Priority:** P1 | **Phase:** 7 | **Blocks:** T-381–T-389

## Why

Every Discord send attempt must be stored. Without an alerts table you can't audit what was sent, when, and whether it succeeded. The dashboard Alerts panel reads from this table.

## Steps

1. Add to `database/schema.sql`:

```sql
-- ============================================================
-- ALERTS — Discord notification log (Phase 7)
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel     VARCHAR(50) NOT NULL,
    title       TEXT NOT NULL,
    message     TEXT,
    color       INT DEFAULT 3447003,     -- Discord blue
    status      VARCHAR(20) NOT NULL DEFAULT 'sent'
                CHECK (status IN ('sent', 'failed', 'skipped')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alerts_channel    ON alerts(channel);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at DESC);
```

2. Create `alembic/versions/0009_add_alerts_table.py`:
```python
"""Add alerts table for Discord notification log (Phase 7).
Revision ID: 0009_add_alerts_table
Revises: 0008_add_tasks_table
Create Date: 2026-05-30
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0009_add_alerts_table"
down_revision: Union[str, None] = "0008_add_tasks_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("color", sa.Integer(), server_default="3447003"),
        sa.Column("status", sa.String(20), nullable=False, server_default="sent"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('sent','failed','skipped')", name="chk_alerts_status"),
    )
    op.create_index("idx_alerts_channel",    "alerts", ["channel"])
    op.create_index("idx_alerts_created_at", "alerts", ["created_at"])

def downgrade() -> None:
    op.drop_index("idx_alerts_created_at")
    op.drop_index("idx_alerts_channel")
    op.drop_table("alerts")
```

## Done When
- `alerts` table in schema.sql with correct columns + indexes
- Alembic 0009 with correct `down_revision = "0008_add_tasks_table"`
- `py_compile` + `ruff check .` passes
- CHANGELOG prepended

---

# T-381 — utils/discord_notifier.py

**Priority:** P1 | **Phase:** 7 | **Depends on:** T-380 | **Blocks:** T-384–T-388

## Why

All Phase 7 alert wiring depends on one reliable Discord send primitive. This module must handle: webhook not configured (silent skip), HTTP error (log + store as failed), and embed formatting for different alert types. It must never crash the pipeline.

## Steps

Create `utils/discord_notifier.py`:

```python
"""
RE_OS — Discord Notifier (Phase 7 — Alerts)
Sends structured embed messages to Discord via webhooks.
All webhook URLs are optional — missing URL = skipped (not an error).

Discord channel map (set webhook URLs in .env):
  rera_yelahanka   → DISCORD_WEBHOOK_RERA_YELAHANKA
  rera_devanahalli → DISCORD_WEBHOOK_RERA_DEVANAHALLI
  rera_hebbal      → DISCORD_WEBHOOK_RERA_HEBBAL
  competitor       → DISCORD_WEBHOOK_COMPETITOR
  price            → DISCORD_WEBHOOK_PRICE
  intel            → DISCORD_WEBHOOK_INTEL
  system           → DISCORD_WEBHOOK_SYSTEM
"""
import json
import os
from datetime import datetime, timezone

from loguru import logger

# Discord embed colour codes
COLOR_GREEN  = 3066993   # #2ecc71
COLOR_RED    = 15158332  # #e74c3c
COLOR_AMBER  = 16750848  # #ffaa00
COLOR_BLUE   = 3447003   # #3498db
COLOR_PURPLE = 10181046  # #9b59b6

_CHANNEL_ENV_MAP = {
    "rera_yelahanka":   "DISCORD_WEBHOOK_RERA_YELAHANKA",
    "rera_devanahalli": "DISCORD_WEBHOOK_RERA_DEVANAHALLI",
    "rera_hebbal":      "DISCORD_WEBHOOK_RERA_HEBBAL",
    "competitor":       "DISCORD_WEBHOOK_COMPETITOR",
    "price":            "DISCORD_WEBHOOK_PRICE",
    "intel":            "DISCORD_WEBHOOK_INTEL",
    "system":           "DISCORD_WEBHOOK_SYSTEM",
}


def _get_webhook_url(channel: str) -> str | None:
    env_key = _CHANNEL_ENV_MAP.get(channel)
    if not env_key:
        return None
    return os.environ.get(env_key) or None


def _log_alert(channel: str, title: str, message: str, color: int, status: str) -> None:
    """Persist alert attempt to DB (non-fatal if DB unavailable)."""
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                INSERT INTO alerts (channel, title, message, color, status)
                VALUES (:channel, :title, :message, :color, :status)
                """),
                {"channel": channel, "title": title,
                 "message": message[:2000] if message else None,
                 "color": color, "status": status},
            )
    except Exception as exc:
        logger.warning(f"[Discord] Failed to log alert to DB: {exc}")


def send(channel: str, title: str, message: str = "", color: int = COLOR_BLUE) -> bool:
    """Send a Discord embed message to the named channel webhook.
    Returns True if sent, False if skipped or failed. Never raises."""
    import urllib.request
    import urllib.error

    url = _get_webhook_url(channel)
    if not url:
        logger.debug(f"[Discord] Channel '{channel}' not configured — skipping alert: {title}")
        _log_alert(channel, title, message, color, "skipped")
        return False

    payload = json.dumps({
        "embeds": [{
            "title": title[:256],
            "description": message[:4096] if message else "",
            "color": color,
            "footer": {"text": "RE_OS · LLS Intelligence"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status in (200, 204):
                logger.info(f"[Discord] Sent to #{channel}: {title}")
                _log_alert(channel, title, message, color, "sent")
                return True
            logger.warning(f"[Discord] Unexpected status {resp.status} for #{channel}")
            _log_alert(channel, title, message, color, "failed")
            return False
    except Exception as exc:
        logger.warning(f"[Discord] Failed to send to #{channel}: {exc}")
        _log_alert(channel, title, message, color, "failed")
        return False


# ── Alert formatters ─────────────────────────────────────────────────────────

def send_rera_alert(market: str, new_count: int, developers: list[str]) -> bool:
    channel = f"rera_{market.lower()}"
    title   = f"🏗 {new_count} new RERA project{'s' if new_count != 1 else ''} — {market}"
    devs    = ", ".join(developers[:5]) + ("…" if len(developers) > 5 else "")
    message = f"**{new_count}** new RERA registration{'s' if new_count != 1 else ''} detected in **{market}**.\nDevelopers: {devs}"
    return send(channel, title, message, COLOR_GREEN)


def send_intel_alert(market: str, run_id: str, synopsis: str, avg_psf: int | None) -> bool:
    psf_str = f"₹{avg_psf:,}/sqft" if avg_psf else "PSF unavailable"
    title   = f"📊 Intel report ready — {market}"
    message = f"**Run:** `{run_id}`\n**Avg PSF:** {psf_str}\n\n{synopsis[:400]}"
    return send("intel", title, message, COLOR_BLUE)


def send_competitor_alert(developer: str, project: str, market: str) -> bool:
    title   = f"👀 New competitor project — {market}"
    message = f"**{developer}** has launched **{project}** in {market}."
    return send("competitor", title, message, COLOR_PURPLE)


def send_price_alert(market: str, old_psf: float, new_psf: float) -> bool:
    delta = ((new_psf - old_psf) / max(old_psf, 1)) * 100
    direction = "↑" if delta > 0 else "↓"
    title   = f"💰 Price movement {direction} {abs(delta):.1f}% — {market}"
    message = (
        f"**{market}** avg listing PSF moved from ₹{old_psf:,.0f} to ₹{new_psf:,.0f} "
        f"({direction}{abs(delta):.1f}%)."
    )
    color = COLOR_RED if delta < 0 else COLOR_GREEN
    return send("price", title, message, color)


def send_system_alert(job_name: str, error: str) -> bool:
    title   = f"⚠ Scheduler error — {job_name}"
    message = f"**Job:** `{job_name}`\n**Error:** {error[:500]}"
    return send("system", title, message, COLOR_RED)
```

2. `py_compile` + `ruff check .` must pass.

## Done When
- `utils/discord_notifier.py` with `send()` + 5 formatter functions
- `send()` returns False (never raises) when webhook not configured
- Alert logged to DB on every send attempt
- `ruff check .` passes
- CHANGELOG prepended

---

# T-382 — settings.py + .env.example — Discord config

**Priority:** P1 | **Phase:** 7 | **Depends on:** T-381

## Steps

1. In `config/settings.py`, add after the existing env vars section:

```python
# ── Discord (Phase 7 — Alerts) ────────────────────────────────────────────────
DISCORD_WEBHOOK_RERA_YELAHANKA   = os.environ.get("DISCORD_WEBHOOK_RERA_YELAHANKA", "")
DISCORD_WEBHOOK_RERA_DEVANAHALLI = os.environ.get("DISCORD_WEBHOOK_RERA_DEVANAHALLI", "")
DISCORD_WEBHOOK_RERA_HEBBAL      = os.environ.get("DISCORD_WEBHOOK_RERA_HEBBAL", "")
DISCORD_WEBHOOK_COMPETITOR       = os.environ.get("DISCORD_WEBHOOK_COMPETITOR", "")
DISCORD_WEBHOOK_PRICE            = os.environ.get("DISCORD_WEBHOOK_PRICE", "")
DISCORD_WEBHOOK_INTEL            = os.environ.get("DISCORD_WEBHOOK_INTEL", "")
DISCORD_WEBHOOK_SYSTEM           = os.environ.get("DISCORD_WEBHOOK_SYSTEM", "")

DISCORD_CHANNELS = {
    "rera_yelahanka":   DISCORD_WEBHOOK_RERA_YELAHANKA,
    "rera_devanahalli": DISCORD_WEBHOOK_RERA_DEVANAHALLI,
    "rera_hebbal":      DISCORD_WEBHOOK_RERA_HEBBAL,
    "competitor":       DISCORD_WEBHOOK_COMPETITOR,
    "price":            DISCORD_WEBHOOK_PRICE,
    "intel":            DISCORD_WEBHOOK_INTEL,
    "system":           DISCORD_WEBHOOK_SYSTEM,
}
```

2. In `.env.example`, add:

```bash
# ── Discord Alerts (Phase 7) ──
# Create a Discord server, add channels, right-click each → Edit Channel → Integrations → Webhooks → New Webhook → Copy URL
# Channel structure: #rera-yelahanka, #rera-devanahalli, #rera-hebbal, #competitor-launches, #price-signals, #intel-reports, #re-os-health
DISCORD_WEBHOOK_RERA_YELAHANKA=
DISCORD_WEBHOOK_RERA_DEVANAHALLI=
DISCORD_WEBHOOK_RERA_HEBBAL=
DISCORD_WEBHOOK_COMPETITOR=
DISCORD_WEBHOOK_PRICE=
DISCORD_WEBHOOK_INTEL=
DISCORD_WEBHOOK_SYSTEM=
```

3. Add all 7 `DISCORD_WEBHOOK_*` keys to `docker-compose.yml` env blocks (both `agents` and `scheduler` services).

## Done When
- `settings.py` has 7 Discord env vars + DISCORD_CHANNELS dict
- `.env.example` has Discord section with setup instructions
- `docker-compose.yml` agents + scheduler env blocks include all 7 keys
- `ruff check .` passes
- CHANGELOG prepended

---

# T-383 — tests/test_discord_notifier.py

**Priority:** P1 | **Phase:** 7 | **Depends on:** T-381

## Steps

Create `tests/test_discord_notifier.py`:

```python
import json
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit

from utils.discord_notifier import (
    send, send_rera_alert, send_intel_alert,
    send_competitor_alert, send_price_alert, send_system_alert,
    COLOR_GREEN, COLOR_RED, COLOR_BLUE,
)


class TestSend:
    def test_skip_when_no_webhook(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("utils.discord_notifier._log_alert") as mock_log:
                result = send("rera_yelahanka", "Test", "body")
                assert result is False
                mock_log.assert_called_once_with("rera_yelahanka", "Test", "body", COLOR_BLUE, "skipped")

    def test_returns_true_on_204(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 204
        with patch.dict("os.environ", {"DISCORD_WEBHOOK_RERA_YELAHANKA": "https://discord.com/fake"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                with patch("utils.discord_notifier._log_alert"):
                    result = send("rera_yelahanka", "Test", "body")
                    assert result is True

    def test_returns_false_on_exception(self):
        with patch.dict("os.environ", {"DISCORD_WEBHOOK_RERA_YELAHANKA": "https://discord.com/fake"}):
            with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
                with patch("utils.discord_notifier._log_alert"):
                    result = send("rera_yelahanka", "Test", "body")
                    assert result is False

    def test_unknown_channel_skipped(self):
        with patch("utils.discord_notifier._log_alert") as mock_log:
            result = send("nonexistent_channel", "Title", "msg")
            assert result is False
            mock_log.assert_called_with("nonexistent_channel", "Title", "msg", COLOR_BLUE, "skipped")


class TestFormatters:
    def test_rera_alert_structure(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_rera_alert("Yelahanka", 5, ["Brigade", "Prestige"])
            call = mock_send.call_args
            assert "rera_yelahanka" == call[0][0]
            assert "5" in call[0][1]

    def test_intel_alert_contains_run_id(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_intel_alert("Yelahanka", "20260530_071726", "Market cooling", 10791)
            call = mock_send.call_args
            assert "20260530_071726" in call[0][2]

    def test_price_alert_color_red_on_decline(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_price_alert("Yelahanka", 10000, 9000)
            call = mock_send.call_args
            assert call[0][3] == COLOR_RED

    def test_price_alert_color_green_on_rise(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_price_alert("Yelahanka", 9000, 10000)
            call = mock_send.call_args
            assert call[0][3] == COLOR_GREEN

    def test_system_alert_structure(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_system_alert("rera_yelahanka", "Connection refused")
            call = mock_send.call_args
            assert "system" == call[0][0]
            assert "Connection refused" in call[0][2]
```

## Done When
- `tests/test_discord_notifier.py` with ≥8 tests, all pass
- `ruff check .` passes
- CHANGELOG prepended

---

# T-384 — Wire RERA alerts to scheduler.py

**Priority:** P1 | **Phase:** 7 | **Depends on:** T-381, T-382

## Steps

1. In `config/scheduler.py`, in `run_single_market_rera()`, after the subprocess is spawned AND completes (add `proc.wait()` with timeout), query the DB for new RERA projects since the job started:

```python
def run_single_market_rera(market: str):
    from config.llm_router import _clear_excluded
    from datetime import datetime, timezone
    import subprocess
    _clear_excluded()
    job_start = datetime.now(timezone.utc)
    logger.info(f"Scheduler: Starting RERA refresh for {market}")
    slug = market.lower().replace(" ", "_")
    log_path = os.path.join("logs", f"{slug}.log")
    os.makedirs("logs", exist_ok=True)
    cmd = [sys.executable, "scrapers/rera_karnataka.py", "--market", market]
    log_fh = open(log_path, "a")
    proc = subprocess.Popen(cmd, env=os.environ, stdout=log_fh, stderr=log_fh)
    log_fh.close()
    logger.info(f"  Spawned RERA process for {market} (PID {proc.pid}) → {log_path}")
    try:
        proc.wait(timeout=1800)   # 30 min max
    except subprocess.TimeoutExpired:
        proc.kill()
        logger.warning(f"  RERA process for {market} timed out — killed")
        return
    # Query new projects since job start
    try:
        from utils.db import get_engine
        from utils.discord_notifier import send_rera_alert
        from sqlalchemy import text
        with get_engine().connect() as conn:
            rows = conn.execute(text("""
                SELECT rp.project_name, d.name AS developer_name
                FROM rera_projects rp
                LEFT JOIN developers d ON d.id = rp.developer_id
                LEFT JOIN micro_markets mm ON mm.id = rp.micro_market_id
                WHERE mm.name ILIKE :market
                  AND rp.created_at >= :job_start
                ORDER BY rp.created_at DESC
                LIMIT 20
            """), {"market": f"%{market}%", "job_start": job_start}).fetchall()
        if rows:
            developers = list({r[1] for r in rows if r[1]})
            send_rera_alert(market, len(rows), developers)
    except Exception as e:
        logger.warning(f"  RERA alert failed for {market}: {e}")
```

2. `py_compile config/scheduler.py` + `ruff check .` must pass.

## Done When
- Scheduler waits for RERA subprocess to complete (30-min timeout)
- Queries new RERA projects since job start
- Calls `send_rera_alert` if count > 0
- `ruff check .` passes
- CHANGELOG prepended

---

# T-385 — Wire Intel report alerts to market_intel_crew.py

**Priority:** P1 | **Phase:** 7 | **Depends on:** T-381

## Steps

1. In `crews/market_intel_crew.py`, after the CEO synthesis saves the report file (Stage 3 success path), add:

```python
try:
    from utils.discord_notifier import send_intel_alert
    from utils.db import get_engine
    from sqlalchemy import text
    # Pull avg_psf from DB for this market
    with get_engine().connect() as _conn:
        row = _conn.execute(text("""
            SELECT ROUND(AVG(l.price_psf))
            FROM listings l
            JOIN micro_markets mm ON mm.id = l.micro_market_id
            WHERE mm.name ILIKE :market AND l.price_psf > 1000 AND l.price_psf < 50000
        """), {"market": f"%{market_name}%"}).fetchone()
    avg_psf = int(row[0]) if row and row[0] else None
    synopsis = ceo_result[:300] if ceo_result else ""
    send_intel_alert(market_name, run_id, synopsis, avg_psf)
except Exception as _e:
    logger.warning(f"Intel alert failed: {_e}")
```

2. `py_compile crews/market_intel_crew.py` + `ruff check .` must pass.

## Done When
- Intel report completion triggers Discord send
- Message contains run_id + synopsis + avg_psf
- Graceful fail (no pipeline abort) if Discord unavailable
- CHANGELOG prepended

---

# T-386 — Wire competitor launch alerts to developer_scout.py

**Priority:** P2 | **Phase:** 7 | **Depends on:** T-381

## Steps

1. In `scrapers/developer_scout.py`, after projects are returned from `scout()`, check the scout memory for truly new CIDs:

```python
try:
    from utils.discord_notifier import send_competitor_alert
    for project in new_projects:   # new_projects = [p for p in projects if sm.is_new(cid)]
        send_competitor_alert(
            developer=project.get("developer_name", "Unknown"),
            project=project.get("project_name", "Unknown"),
            market=market,
        )
except Exception as _e:
    pass  # Alert failure must not break scout
```

2. This requires access to which projects are truly new (not in scout_memory). Use the `is_new` flag already returned by `scout_memory.mark_all()`.

## Done When
- New developer projects trigger Discord alert
- Uses existing scout_memory new-flag logic
- `ruff check .` passes
- CHANGELOG prepended

---

# T-387 — Wire price movement alerts to portal_scout.py

**Priority:** P2 | **Phase:** 7 | **Depends on:** T-381

## Steps

1. In `scrapers/portal_scout.py`, after listings are saved, compute avg_psf and compare to last `market_snapshots` entry:

```python
try:
    from utils.db import get_engine
    from utils.discord_notifier import send_price_alert
    from sqlalchemy import text
    with get_engine().connect() as conn:
        prev = conn.execute(text("""
            SELECT avg_psf_sale FROM market_snapshots
            WHERE micro_market_id = (SELECT id FROM micro_markets WHERE name ILIKE :m)
            ORDER BY snapshot_date DESC LIMIT 1
        """), {"m": f"%{market}%"}).fetchone()
        curr = conn.execute(text("""
            SELECT ROUND(AVG(price_psf)) FROM listings l
            JOIN micro_markets mm ON mm.id = l.micro_market_id
            WHERE mm.name ILIKE :m AND price_psf > 1000 AND price_psf < 50000
        """), {"m": f"%{market}%"}).fetchone()
    if prev and prev[0] and curr and curr[0]:
        old_psf, new_psf = float(prev[0]), float(curr[0])
        if abs((new_psf - old_psf) / max(old_psf, 1)) >= 0.05:
            send_price_alert(market, old_psf, new_psf)
except Exception:
    pass
```

## Done When
- Portal scout triggers price alert when PSF delta ≥ 5%
- Graceful fail on any error
- `ruff check .` passes
- CHANGELOG prepended

---

# T-388 — Wire system health alerts to scheduler.py exception handler

**Priority:** P1 | **Phase:** 7 | **Depends on:** T-381

## Steps

1. In `config/scheduler.py`, wrap the three market RERA jobs and the `run_market_snapshot` function with a shared error handler:

```python
def _safe_job(fn, job_name: str, *args, **kwargs):
    """Run a scheduler job. Send Discord system alert on exception."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.error(f"[Scheduler] Job '{job_name}' failed: {exc}")
        try:
            from utils.discord_notifier import send_system_alert
            send_system_alert(job_name, str(exc)[:300])
        except Exception:
            pass
        raise
```

2. Wrap the `run_market_snapshot` call:
```python
scheduler.add_job(
    lambda: _safe_job(run_market_snapshot, "market_snapshot"),
    ...
)
```

3. `py_compile config/scheduler.py` + `ruff check .` must pass.

## Done When
- Scheduler job exceptions trigger Discord system alert
- `_safe_job` wrapper used for all cron jobs
- `ruff check .` passes
- CHANGELOG prepended

---

# T-389 — /api/alerts endpoint + Dashboard Alerts panel

**Priority:** P2 | **Phase:** 7 | **Depends on:** T-380

## Steps

1. In `dashboard/app.py`:

```python
@limiter.limit("30 per minute")
@app.route("/api/alerts", methods=["GET"])
def list_alerts():
    channel_filter = request.args.get("channel")
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        where = "WHERE channel = %s" if channel_filter else ""
        params = [channel_filter] if channel_filter else []
        cur.execute(
            f"SELECT id, channel, title, status, created_at FROM alerts "
            f"{where} ORDER BY created_at DESC LIMIT 50",
            params,
        )
        rows = [
            {"id": str(r[0]), "channel": r[1], "title": r[2],
             "status": r[3], "created_at": r[4].isoformat() if r[4] else None}
            for r in cur.fetchall()
        ]
        cur.close()
        return jsonify({"alerts": rows})
    except Exception as e:
        exc = True
        logger.error("[list_alerts] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)
```

2. Add `/api/alerts` to `_READ_ONLY_PATHS`.

3. Add to `index.html`:

```html
<div class="infra-section">
  <div class="infra-title">ALERTS
    <button class="db-explorer-refresh" onclick="pollAlerts()" title="Refresh">⟳</button>
  </div>
  <div id="alerts-list" style="max-height:200px;overflow-y:auto;"></div>
  <div id="alerts-status" style="color:#6b7280;font-size:8px;margin-top:4px;"></div>
</div>
```

4. Add JS:
```javascript
const _ALERT_CHANNEL_COLORS = {
  rera_yelahanka: '#3fb950', rera_devanahalli: '#58a6ff', rera_hebbal: '#9b7ec7',
  competitor: '#f0a020', price: '#f85149', intel: '#58a6ff', system: '#f85149',
};
async function pollAlerts() {
  try {
    const data = await fetch('/api/alerts').then(r => r.json());
    const list = document.getElementById('alerts-list');
    const statusEl = document.getElementById('alerts-status');
    if (!data.alerts || !data.alerts.length) {
      list.innerHTML = '<div style="color:#484f58;font-size:8px;padding:4px;">No alerts yet — configure Discord webhooks in .env</div>';
      return;
    }
    list.innerHTML = data.alerts.map(a => {
      const color = _ALERT_CHANNEL_COLORS[a.channel] || '#8b949e';
      const st = a.status === 'sent' ? '✓' : a.status === 'failed' ? '✗' : '–';
      const ts = a.created_at ? new Date(a.created_at).toLocaleTimeString('en-IN', {hour12:false}) : '';
      return `<div style="display:flex;gap:6px;padding:4px 0;border-bottom:1px solid #1a2235;font-size:8px;align-items:flex-start;">
        <span style="color:${color};font-family:'Press Start 2P',cursive;font-size:6px;flex-shrink:0;padding-top:2px;">${escapeHtml(a.channel.replace('_',' '))}</span>
        <span style="flex:1;color:#c9d1d9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(a.title)}</span>
        <span style="color:${a.status==='sent'?'#3fb950':a.status==='failed'?'#f85149':'#6b7280'};flex-shrink:0;">${st}</span>
        <span style="color:#484f58;flex-shrink:0;">${ts}</span>
      </div>`;
    }).join('');
    statusEl.textContent = 'Updated ' + new Date().toLocaleTimeString('en-IN', {hour12:false});
    markUpdated('alerts');
  } catch (e) { /* silent */ }
}
pollAlerts();
setInterval(pollAlerts, 60000);
```

## Done When
- `/api/alerts` returns last 50 alerts
- Alerts panel visible in dashboard with colour-coded channel labels
- Empty state message mentions Discord webhook setup
- `ruff check .` passes
- CHANGELOG prepended

---

# Sprint 26 Briefs (archived)

---

# T-281 — RERA Scraper: Fix Yelahanka + Hebbal Locality Selectors

> **If you are reading this without first marking your task `IN_PROGRESS` in `TASK_QUEUE.md` — stop. Go do that first. Then come back.**

1. Mark task `IN_PROGRESS` in `TASK_QUEUE.md` (write the file, save it).
2. Find your task ID in this file and jump to that section.
3. Read the brief fully before writing a single line of code.
4. Follow the steps in order. Do not skip.
5. Run the "Done when" checks. All must pass before marking DONE.
6. Write the CHANGELOG.md entry and update TASK_QUEUE.md status to `DONE`.

---

## Operating Standard

Both brains execute at the level of a **senior tech product engineering lead**. That means:

- You understand why the change exists before making it, not just what to change.
- You do not introduce regressions. You check first, change second.
- You do not over-engineer. The smallest correct change wins.
- You do not leave the codebase in a worse state than you found it. If you see a problem adjacent to your task, note it in TASK_QUEUE.md — do not fix it unless it blocks your task.
- You test your own work. "It looks right" is not a done criterion.
- You write one precise CHANGELOG.md entry per task. No summaries of intent — only concrete changes made.

---

## System Context (read once, applies to all tasks)

**Stack:** 5-container Docker Compose — postgres/PostGIS, ollama, redis, agents (Flask :8050), scheduler.
**Pipeline:** 3-stage — Scrape (LLM) → DB Organizer (Python) → Intel (LLM).
**LLM tiers:** HEAVY (Groq → Gemini → NVIDIA → OpenRouter → Ollama), ANALYSIS (Cerebras → Groq → Gemini → NVIDIA → Ollama), LIGHT (Cerebras → Gemma → NVIDIA → Ollama).
**Working dir:** `/app` inside containers. Host mirror: `D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS`.
**Run tests:** `docker compose exec agents pytest tests/ -q` or `pytest tests/ -q` with DB_PASSWORD set.
**Lint:** `ruff check .` and `ruff format --check .` — both must pass clean.
**CHANGELOG format:** `TYPE | file/path | what changed | who | YYYY-MM-DD`

---

---

# Sprint 26 Briefs

---

# T-352 — DB: tasks table

**Priority:** P1 | **Phase:** 3 Closure | **Blocks:** T-353, T-354, T-355

## Why

Board Room extracts action items from each session. Right now they exist only in the transcript JSON — there is nowhere to store them as first-class records. The Task Board (T-354) and the action approval UI (T-355) both need a `tasks` table before any frontend work can start. This is the data foundation for Phase 3 DoD.

## Steps

1. **Add to `database/schema.sql`** — new table at the bottom, before the VIEWS block:
```sql
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    owner           VARCHAR(50),           -- bd | finance | engineering | ops | legal | ceo
    status          VARCHAR(20) NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'active', 'done', 'failed', 'rejected')),
    priority        VARCHAR(10) NOT NULL DEFAULT 'medium'
                    CHECK (priority IN ('high', 'medium', 'low')),
    source_type     VARCHAR(30),           -- board_session | manual | scheduler
    source_id       UUID,                  -- board_sessions.session_id if source_type=board_session
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tasks_status    ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_owner     ON tasks(owner);
CREATE INDEX IF NOT EXISTS idx_tasks_source    ON tasks(source_type, source_id);
```

2. **Create `alembic/versions/0008_add_tasks_table.py`**:
```python
"""Add tasks table for Task Board (Phase 3 closure).

Revision ID: 0008_add_tasks_table
Revises: 0007_add_legal_response
Create Date: 2026-05-30
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0008_add_tasks_table"
down_revision: Union[str, None] = "0007_add_legal_response"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(50)),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("priority", sa.String(10), nullable=False, server_default="medium"),
        sa.Column("source_type", sa.String(30)),
        sa.Column("source_id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('queued','active','done','failed','rejected')", name="chk_tasks_status"),
        sa.CheckConstraint("priority IN ('high','medium','low')", name="chk_tasks_priority"),
    )
    op.create_index("idx_tasks_status", "tasks", ["status"])
    op.create_index("idx_tasks_owner",  "tasks", ["owner"])
    op.create_index("idx_tasks_source", "tasks", ["source_type", "source_id"])

def downgrade() -> None:
    op.drop_index("idx_tasks_source")
    op.drop_index("idx_tasks_owner")
    op.drop_index("idx_tasks_status")
    op.drop_table("tasks")
```

3. **`py_compile`** both files. **`ruff check .`** must pass.

## Done When
- `tasks` table in `schema.sql` with correct columns, CHECK constraints, 3 indexes
- Alembic `0008_add_tasks_table.py` with correct `down_revision = "0007_add_legal_response"`
- `py_compile` passes on migration file
- `ruff check .` passes
- CHANGELOG prepended

---

# T-353 — API: POST /api/tasks + GET /api/tasks

**Priority:** P1 | **Phase:** 3 Closure | **Depends on:** T-352 | **Blocks:** T-354, T-355

## Why

The Task Board and the Board Room approval UI both need two endpoints: one to create a task (approve button calls it), one to list tasks (Task Board reads it). Both are simple CRUD — no LLM, no external calls.

## Steps

1. **Add `/api/tasks/` to `_READ_ONLY_PATHS`** in `dashboard/app.py` (GET is read-only):
```python
_READ_ONLY_PATHS = frozenset({
    ...,
    '/api/tasks',
})
```

2. **Add `GET /api/tasks`** to `dashboard/app.py`:
```python
@limiter.limit("60 per minute")
@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    status_filter = request.args.get("status")          # optional ?status=queued
    owner_filter  = request.args.get("owner")           # optional ?owner=bd
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        where_clauses, params = [], []
        if status_filter:
            where_clauses.append("status = %s")
            params.append(status_filter)
        if owner_filter:
            where_clauses.append("owner = %s")
            params.append(owner_filter)
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        cur.execute(
            f"SELECT id, title, owner, status, priority, source_type, source_id, created_at "
            f"FROM tasks {where_sql} ORDER BY created_at DESC LIMIT 200",
            params,
        )
        rows = [
            {"id": str(r[0]), "title": r[1], "owner": r[2], "status": r[3],
             "priority": r[4], "source_type": r[5],
             "source_id": str(r[6]) if r[6] else None,
             "created_at": r[7].isoformat() if r[7] else None}
            for r in cur.fetchall()
        ]
        cur.close()
        return jsonify({"tasks": rows})
    except Exception as e:
        exc = True
        logger.error("[list_tasks] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)
```

3. **Add `POST /api/tasks`** (auth-gated — write endpoint):
```python
@limiter.limit("30 per minute")
@app.route("/api/tasks", methods=["POST"])
def create_task():
    payload = request.get_json() or {}
    title    = str(payload.get("title") or "").strip()
    owner    = str(payload.get("owner") or "").strip()[:50]
    priority = str(payload.get("priority") or "medium").strip()
    source_type = str(payload.get("source_type") or "").strip()[:30]
    source_id_raw = payload.get("source_id")

    if not title:
        return jsonify({"error": "title required"}), 400
    if priority not in ("high", "medium", "low"):
        priority = "medium"

    import uuid as _uuid
    try:
        source_id = _uuid.UUID(str(source_id_raw)) if source_id_raw else None
    except ValueError:
        source_id = None

    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO tasks (title, owner, priority, source_type, source_id)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (title, owner or None, priority, source_type or None, source_id),
        )
        task_id = str(cur.fetchone()[0])
        conn.commit()
        cur.close()
        return jsonify({"task_id": task_id, "status": "queued"}), 201
    except Exception as e:
        exc = True
        logger.error("[create_task] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)
```

4. **Add `PATCH /api/tasks/<task_id>`** (status update — approve/reject/done):
```python
@limiter.limit("60 per minute")
@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id):
    payload = request.get_json() or {}
    new_status = str(payload.get("status") or "").strip()
    if new_status not in ("queued", "active", "done", "failed", "rejected"):
        return jsonify({"error": "invalid status"}), 400
    import uuid as _uuid
    try:
        tid = _uuid.UUID(task_id)
    except ValueError:
        return jsonify({"error": "invalid task_id"}), 400
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE tasks SET status = %s, updated_at = NOW() WHERE id = %s RETURNING id",
            (new_status, tid),
        )
        if cur.fetchone() is None:
            return jsonify({"error": "not found"}), 404
        conn.commit()
        cur.close()
        return jsonify({"status": new_status})
    except Exception as e:
        exc = True
        logger.error("[update_task] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)
```

5. **`py_compile dashboard/app.py`** + **`ruff check .`** must pass.

## Done When
- `GET /api/tasks` returns `{"tasks": [...]}` with status/owner filter support
- `POST /api/tasks` creates a row and returns `{"task_id": "...", "status": "queued"}`
- `PATCH /api/tasks/<id>` updates status
- `/api/tasks` in `_READ_ONLY_PATHS`
- `ruff check .` passes
- CHANGELOG prepended

---

# T-354 — Dashboard Task Board panel

**Priority:** P1 | **Phase:** 3 Closure | **Depends on:** T-353

## Why

Phase 3 DoD requires approved actions to be "visible on Task Board." The Task Board is the final missing Phase 2/3 UI panel. It must render tasks from `/api/tasks` as a Kanban with four status columns.

## Steps

1. **Add a new `infra-section` div** in `dashboard/templates/index.html` in the right panel, after the Board Room section:
```html
<div class="infra-section">
  <div class="infra-title">TASK BOARD
    <button class="db-explorer-refresh" onclick="pollTasks()" title="Refresh">⟳</button>
  </div>
  <div style="display:flex;gap:6px;overflow-x:auto;" id="task-board-columns">
    <!-- populated by JS -->
  </div>
  <div id="task-board-status" style="color:#6b7280;font-size:8px;margin-top:4px;"></div>
</div>
```

2. **Add CSS** for task cards (in the `<style>` block):
```css
.task-col { flex: 1; min-width: 80px; }
.task-col-header { font-family: 'Press Start 2P', cursive; font-size: 7px; color: #8b949e; padding: 4px 0; letter-spacing: 1px; border-bottom: 1px solid #2a3a55; margin-bottom: 4px; }
.task-col-header.col-queued { color: #8b949e; }
.task-col-header.col-active { color: #f0a020; }
.task-col-header.col-done   { color: #3fb950; }
.task-col-header.col-failed { color: #f85149; }
.task-card { background: #131c2e; border: 1px solid #2a3a55; border-radius: 4px; padding: 5px 6px; margin-bottom: 4px; font-size: 8px; line-height: 1.4; }
.task-card .tc-title { color: #c9d1d9; margin-bottom: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-card .tc-meta  { color: #6b7280; font-size: 7px; }
.task-priority-high   { border-left: 2px solid #f85149; }
.task-priority-medium { border-left: 2px solid #f0a020; }
.task-priority-low    { border-left: 2px solid #3fb950; }
```

3. **Add JS** (near the bottom of the script block, after DB Explorer):
```javascript
// ── Task Board ──
const _TASK_STATUSES = ['queued', 'active', 'done', 'failed'];
const _TASK_STATUS_LABELS = { queued: 'QUEUED', active: 'ACTIVE', done: 'DONE', failed: 'FAILED' };
let _tasksCache = [];

async function pollTasks() {
  const statusEl = document.getElementById('task-board-status');
  try {
    const data = await fetch('/api/tasks').then(r => r.json());
    if (data.error) { statusEl.textContent = 'Error: ' + data.error; return; }
    _tasksCache = data.tasks || [];
    _renderTaskBoard();
    statusEl.textContent = 'Updated ' + new Date().toLocaleTimeString('en-IN', { hour12: false });
    markUpdated('task-board');
  } catch (e) {
    statusEl.textContent = 'Unavailable';
  }
}

function _renderTaskBoard() {
  const col = document.getElementById('task-board-columns');
  const byStatus = {};
  _TASK_STATUSES.forEach(s => { byStatus[s] = []; });
  _tasksCache.forEach(t => { if (byStatus[t.status]) byStatus[t.status].push(t); });

  col.innerHTML = _TASK_STATUSES.map(status => {
    const tasks = byStatus[status];
    const cards = tasks.length
      ? tasks.map(t => {
          const pri = t.priority || 'medium';
          const owner = t.owner ? `<span style="color:#58a6ff;">${escapeHtml(t.owner.toUpperCase())}</span> · ` : '';
          return `<div class="task-card task-priority-${escapeHtml(pri)}">
            <div class="tc-title" title="${escapeHtml(t.title)}">${escapeHtml(t.title)}</div>
            <div class="tc-meta">${owner}${escapeHtml(pri)}</div>
          </div>`;
        }).join('')
      : '<div style="color:#484f58;font-size:7px;padding:4px 0;">empty</div>';
    return `<div class="task-col">
      <div class="task-col-header col-${escapeHtml(status)}">${_TASK_STATUS_LABELS[status]} <span style="color:#484f58;">(${tasks.length})</span></div>
      ${cards}
    </div>`;
  }).join('');
}

pollTasks();
setInterval(pollTasks, 30000);
```

4. **`py_compile`** + **`ruff check .`** must pass (no Python changes, but verify no lint breakage).

## Done When
- Task Board panel visible in dashboard with 4 status columns
- Tasks from `/api/tasks` render as cards with title, owner, priority colour
- 30s auto-refresh working
- Empty columns show "empty" placeholder
- CHANGELOG prepended

---

# T-355 — Board Room: action approval UI

**Priority:** P1 | **Phase:** 3 Closure | **Depends on:** T-353

## Why

Phase 3 DoD: "two action items approved and visible on Task Board." Right now `_renderBoardResult` displays actions as a read-only list. Each action needs an Approve button that calls `POST /api/tasks` and creates a queued task. This is the final user-facing closure for Phase 3.

## Steps

1. **In `_renderBoardResult`** in `dashboard/templates/index.html`, find where actions are rendered and add Approve/Reject buttons. The actions section currently renders from `transcript.actions`. Change it to:

```javascript
// Inside _renderBoardResult, actions section:
if (transcript.actions && transcript.actions.length) {
  html += '<div style="margin-top:10px;border-top:1px solid #2a3a55;padding-top:8px;">';
  html += '<div style="font-family:\'Press Start 2P\',cursive;font-size:7px;color:#f0a020;margin-bottom:6px;">ACTION ITEMS</div>';
  transcript.actions.forEach((a, i) => {
    const pri = a.priority || 'medium';
    const owner = a.owner || 'ceo';
    html += `<div id="action-row-${i}" style="display:flex;align-items:flex-start;gap:6px;margin-bottom:6px;padding:5px 6px;background:#0f1520;border:1px solid #2a3a55;border-radius:4px;">
      <div style="flex:1;font-size:9px;color:#c9d1d9;">${escapeHtml(a.action || '')}<br>
        <span style="font-size:7px;color:#6b7280;">${escapeHtml(owner.toUpperCase())} · ${escapeHtml(pri)}</span>
      </div>
      <button onclick="approveAction(${i}, ${JSON.stringify(a)})" style="background:#1a3a1a;border:1px solid #3fb950;color:#3fb950;font-size:7px;padding:3px 6px;cursor:pointer;border-radius:3px;white-space:nowrap;">✓ APPROVE</button>
      <button onclick="rejectAction(${i})" style="background:#1a1010;border:1px solid #484f58;color:#6b7280;font-size:7px;padding:3px 6px;cursor:pointer;border-radius:3px;white-space:nowrap;">✗</button>
    </div>`;
  });
  html += '</div>';
}
```

2. **Add `approveAction` + `rejectAction` functions** in the script block:
```javascript
async function approveAction(idx, action) {
  const btn = document.querySelector(`#action-row-${idx} button`);
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  try {
    const apiKey = _getApiKey();
    const r = await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
      body: JSON.stringify({
        title: action.action,
        owner: action.owner || 'ceo',
        priority: action.priority || 'medium',
        source_type: 'board_session',
      }),
    });
    const data = await r.json();
    if (data.task_id) {
      const row = document.getElementById(`action-row-${idx}`);
      if (row) row.style.opacity = '0.5';
      if (btn) { btn.textContent = '✓ QUEUED'; btn.style.color = '#3fb950'; }
      pollTasks();  // refresh task board
    } else {
      if (btn) { btn.disabled = false; btn.textContent = '✓ APPROVE'; }
    }
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = '✓ APPROVE'; }
  }
}

function rejectAction(idx) {
  const row = document.getElementById(`action-row-${idx}`);
  if (row) { row.style.opacity = '0.3'; row.style.pointerEvents = 'none'; }
}
```

3. **`py_compile`** + **`ruff check .`** must pass.

## Done When
- Approve/Reject buttons visible on every action item after board session completes
- Approve calls `POST /api/tasks` → task appears in Task Board QUEUED column
- Reject dims the action row
- CHANGELOG prepended

---

# T-356 — GATE-10: Phase 3 DoD validation

**Priority:** P0 | **Phase:** 3 Closure | **Depends on:** T-352, T-353, T-354, T-355

## Why

This is the formal gate that closes Phase 3. Must be run live against the running stack. Document the result in CHANGELOG with evidence.

## Steps

1. Start the stack: `docker compose up -d`
2. Verify alembic ran: `docker compose exec agents alembic current` — must show `0008_add_tasks_table`
3. Open `http://localhost:8050` — verify Task Board panel is visible
4. Submit a Board Room pitch: market=Yelahanka, pitch="Should LLS enter Yelahanka at ₹6500 PSF via JD model?"
5. Poll session until `status: complete`
6. Verify 5 dept responses visible (BD/Finance/Engineering/Ops/Legal)
7. Approve 2 action items
8. Verify both tasks appear in Task Board QUEUED column
9. Document: session_id, dept count, action count, task_ids in CHANGELOG

## Done When
- All 9 steps above pass
- CHANGELOG entry with session_id, evidence of 5 dept responses, 2 task_ids created
- TASK_QUEUE.md GATE-10 marked PASSED
- `VISION.md` Phase 3 status updated from 🟡 → ✅ (by T-364)

---

# T-357 — Dashboard Org Chart panel

**Priority:** P2 | **Phase:** 2 Polish

## Why

Phase 2 DoD mentions "org chart with live agent states." The current dashboard has static cabin cards hardcoded in HTML. This task replaces the static layout with a registry-driven org chart that builds from `/api/agents` data — so any future agent additions show up automatically.

## Steps

1. Add a new panel section at the top of the office floor (or as a dedicated infra panel) that fetches `/api/agents` and renders agent cards as a tree:
   - CEO at top
   - Analyst / Scout / Processor / Sentinel below
2. Each card: agent name, role, status badge (colour-coded: IDLE=grey, RUNNING=amber, DONE=green)
3. `last_action` text truncated to 40 chars
4. Clicking a card opens the existing command panel for that agent
5. Remove or reduce the existing hardcoded cabin HTML redundancy — the Org Chart panel should be the single authoritative view; the old cabins can remain as the "mission control" aesthetic layer but Org Chart is the data layer

## Done When
- Org chart renders from live `/api/agents` data
- Status badges colour-correct
- Works when DB is unavailable (falls back to in-memory states)
- CHANGELOG prepended

---

# T-358 — Board Room 5-column response layout

**Priority:** P2 | **Phase:** 3 Polish

## Why

The Board Room renders 5 dept responses stacked vertically. At full session width it should be a 5-column side-by-side panel so Jinu can compare all dept heads at a glance — that is the original VISION.md spec ("one column per department"). Vertical stack was the v1 implementation; this closes the spec gap.

## Steps

1. In `_renderBoardResult`, change the outer container to `display:grid;grid-template-columns:repeat(5,1fr);gap:8px;`
2. Each dept response in its own column with header (`BD` / `FINANCE` / `ENG` / `OPS` / `LEGAL`) in the department's accent colour
3. Action items stay below the grid as a full-width row
4. On narrow viewport (infra panel is 35% of screen) fall back to `grid-template-columns:1fr 1fr;` via a max-width media query

## Done When
- Board Room result renders as 5 columns side-by-side
- Each column has coloured header
- Actions row is full-width below the grid
- CHANGELOG prepended

---

# T-359 — DB: regulatory_zones seed data

**Priority:** P1 | **Phase:** 5 Bootstrap | **Blocks:** T-360

## Why

Phase 5 (Engineering Dept) builds an FSI calculator. The `regulatory_zones` table already exists in the schema but has no data. The Architect Agent needs zone rules (FAR, max height, setbacks) for the 3 primary markets before any FSI calculation can return real results.

## Steps

1. Check existing `regulatory_zones` schema: `\d regulatory_zones` via MCP postgres tool
2. Seed rows for 3 markets × 3 zone types (Residential/Commercial/Mixed):

| market | zone | far | max_height_m | plot_coverage | setback_front_m | setback_side_m |
|--------|------|-----|-------------|---------------|-----------------|----------------|
| Yelahanka | R1 Residential | 1.75 | 11 | 0.50 | 3.0 | 1.5 |
| Yelahanka | R2 High-Density | 2.50 | 18 | 0.55 | 4.5 | 1.5 |
| Yelahanka | C1 Commercial | 2.25 | 15 | 0.60 | 6.0 | 3.0 |
| Devanahalli | R1 Residential | 2.00 | 14 | 0.50 | 3.0 | 1.5 |
| Devanahalli | R2 High-Density | 3.00 | 24 | 0.60 | 4.5 | 1.5 |
| Devanahalli | C1 Commercial | 2.50 | 18 | 0.65 | 6.0 | 3.0 |
| Hebbal | R1 Residential | 1.75 | 14 | 0.50 | 3.0 | 1.5 |
| Hebbal | R2 High-Density | 2.75 | 21 | 0.58 | 4.5 | 1.5 |
| Hebbal | C1 Commercial | 2.50 | 18 | 0.60 | 6.0 | 3.0 |

3. Create `database/seed_regulatory_zones.sql` with INSERT statements and a verification SELECT
4. Apply via MCP postgres tool or `docker compose exec postgres psql -U re_os_user -d re_os -f /tmp/seed.sql`

## Done When
- 9 rows confirmed in `regulatory_zones` via SELECT
- `seed_regulatory_zones.sql` committed to `database/`
- CHANGELOG prepended

---

# T-360 — utils/fsi_calculator.py — FSICalculator + TypologyRecommender

**Priority:** P1 | **Phase:** 5 Bootstrap | **Depends on:** T-359 | **Blocks:** T-361, T-362

## Why

The Architect Agent (T-361) needs pure-Python tools it can call without an LLM call. FSI calculation and unit mix recommendation are deterministic — they should not consume tokens. This module is the computational core of the Engineering Department.

## Steps

1. Create `utils/fsi_calculator.py`:

```python
from dataclasses import dataclass
from typing import Optional

# BDA zone parameters — updated from regulatory_zones seed (T-359)
_ZONE_RULES: dict[str, dict] = {
    "R1": {"far": 1.75, "max_height_m": 11,  "plot_coverage": 0.50, "setback_front": 3.0, "setback_side": 1.5},
    "R2": {"far": 2.50, "max_height_m": 18,  "plot_coverage": 0.55, "setback_front": 4.5, "setback_side": 1.5},
    "C1": {"far": 2.25, "max_height_m": 15,  "plot_coverage": 0.60, "setback_front": 6.0, "setback_side": 3.0},
}

# PSF band → unit mix recommendation (North Bengaluru market)
_PSF_UNIT_MIX: list[tuple[tuple, dict]] = [
    ((0,    4500), {"1bhk": 30, "2bhk": 55, "3bhk": 15}),  # affordable
    ((4500, 7000), {"1bhk": 15, "2bhk": 55, "3bhk": 30}),  # mid-range
    ((7000, 9999999), {"1bhk": 5, "2bhk": 45, "3bhk": 50}), # premium
]

@dataclass
class FSIResult:
    zone: str
    land_area_sqft: float
    far: float
    buildable_area_sqft: float
    sellable_area_sqft: float   # 65% efficiency default
    max_floors: int
    plot_coverage: float
    setback_front_m: float
    setback_side_m: float

@dataclass
class UnitMix:
    psf_band: str
    bhk_1_pct: int
    bhk_2_pct: int
    bhk_3_pct: int
    recommended_avg_carpet_sqft: int

def calculate_fsi(land_area_sqft: float, zone: str = "R2",
                  efficiency: float = 0.65) -> FSIResult:
    zone = zone.upper()
    rules = _ZONE_RULES.get(zone, _ZONE_RULES["R2"])
    buildable = max(land_area_sqft, 0) * rules["far"]
    sellable  = buildable * max(0.01, min(efficiency, 1.0))
    floor_plate = land_area_sqft * rules["plot_coverage"]
    max_floors  = max(1, int(buildable / max(floor_plate, 1)))
    return FSIResult(
        zone=zone,
        land_area_sqft=land_area_sqft,
        far=rules["far"],
        buildable_area_sqft=round(buildable, 1),
        sellable_area_sqft=round(sellable, 1),
        max_floors=max_floors,
        plot_coverage=rules["plot_coverage"],
        setback_front_m=rules["setback_front"],
        setback_side_m=rules["setback_side"],
    )

def recommend_unit_mix(avg_listing_psf: float) -> UnitMix:
    mix = _PSF_UNIT_MIX[-1][1]
    band = "premium"
    for (lo, hi), m in _PSF_UNIT_MIX:
        if lo <= avg_listing_psf < hi:
            mix = m
            band = "affordable" if hi <= 4500 else ("mid-range" if hi <= 7000 else "premium")
            break
    avg_carpet = 650 if band == "affordable" else (850 if band == "mid-range" else 1100)
    return UnitMix(
        psf_band=band,
        bhk_1_pct=mix["1bhk"],
        bhk_2_pct=mix["2bhk"],
        bhk_3_pct=mix["3bhk"],
        recommended_avg_carpet_sqft=avg_carpet,
    )
```

2. **`py_compile`** + **`ruff check .`** must pass.

## Done When
- `utils/fsi_calculator.py` created with `FSIResult`, `UnitMix`, `calculate_fsi()`, `recommend_unit_mix()`
- Zone lookup defaults to R2 when zone not found
- Negative land area returns buildable_area=0 (guard via `max(land_area_sqft, 0)`)
- `ruff check .` passes
- CHANGELOG prepended

---

# T-361 — agents/architect_agent.py

**Priority:** P1 | **Phase:** 5 Bootstrap | **Depends on:** T-360 | **Blocks:** T-363

## Why

Phase 5 goal: given land data, Architect Agent returns a buildable typology. This is the first Engineering Dept agent. It wraps the two pure-Python tools (FSICalculatorTool + TypologyRecommenderTool) into a CrewAI Agent so it can be called standalone or wired into Board Room later (T-363).

## Steps

1. Create `agents/architect_agent.py`:

```python
"""
RE_OS — Architect Agent (Phase 5 — Engineering Dept)
Standalone or Board Room Engineering supplement.
Given land_area_sqft + zone + avg_listing_psf → FSI calc + unit mix recommendation.
"""
import json
from crewai.tools import BaseTool
from crewai import Agent
from config.llm_router import get_analysis_llm
from utils.fsi_calculator import calculate_fsi, recommend_unit_mix


class FSICalculatorTool(BaseTool):
    name: str = "fsi_calculator"
    description: str = (
        "Calculate buildable area, sellable area, max floors, and plot coverage "
        "for a land parcel. Input: JSON with 'land_area_sqft' (float), "
        "'zone' (R1/R2/C1, default R2), 'efficiency' (0.5–0.75, default 0.65). "
        "Returns FSI result as JSON."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON input"})
        try:
            result = calculate_fsi(
                land_area_sqft=float(params.get("land_area_sqft", 0)),
                zone=str(params.get("zone", "R2")),
                efficiency=float(params.get("efficiency", 0.65)),
            )
            return json.dumps({
                "zone": result.zone,
                "land_area_sqft": result.land_area_sqft,
                "buildable_area_sqft": result.buildable_area_sqft,
                "sellable_area_sqft": result.sellable_area_sqft,
                "max_floors": result.max_floors,
                "far": result.far,
                "plot_coverage_pct": round(result.plot_coverage * 100),
                "setback_front_m": result.setback_front_m,
                "setback_side_m": result.setback_side_m,
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})


class TypologyRecommenderTool(BaseTool):
    name: str = "typology_recommender"
    description: str = (
        "Recommend unit mix (1BHK/2BHK/3BHK split) for a market PSF band. "
        "Input: JSON with 'avg_listing_psf' (float). "
        "Returns unit mix percentages and average carpet area recommendation."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON input"})
        try:
            result = recommend_unit_mix(float(params.get("avg_listing_psf", 5000)))
            return json.dumps({
                "psf_band": result.psf_band,
                "unit_mix": {
                    "1bhk_pct": result.bhk_1_pct,
                    "2bhk_pct": result.bhk_2_pct,
                    "3bhk_pct": result.bhk_3_pct,
                },
                "recommended_avg_carpet_sqft": result.recommended_avg_carpet_sqft,
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})


def create_architect_agent() -> Agent:
    return Agent(
        role="Principal Architect — Engineering Division",
        goal=(
            "Given land area, zone, and market PSF, produce a buildable typology: "
            "FSI analysis, unit mix, floor count, and setback compliance summary."
        ),
        backstory=(
            "Senior architect with 15 years designing residential projects across North Bengaluru. "
            "Understands BDA master plan zones, FAR constraints, RERA unit-mix requirements, "
            "and how to squeeze maximum sellable area from a site without violating setbacks. "
            "Starts every analysis from first principles: land area → buildable area → sellable area → unit mix. "
            "Output is always a structured brief Jinu can hand directly to a structural engineer."
        ),
        tools=[FSICalculatorTool(), TypologyRecommenderTool()],
        llm=get_analysis_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )
```

2. **`py_compile agents/architect_agent.py`** + **`ruff check .`** must pass.

## Done When
- `agents/architect_agent.py` created with both tool classes + `create_architect_agent()`
- `py_compile` passes
- `ruff check .` passes
- CHANGELOG prepended

---

# T-362 — tests/test_fsi_calculator.py

**Priority:** P1 | **Phase:** 5 Bootstrap | **Depends on:** T-360 | **Gates:** GATE-11

## Why

FSI calculation and unit mix are deterministic. If the math is wrong, the Architect Agent gives wrong typology advice to Jinu. These must have unit tests. GATE-11 requires ≥12 passing tests before Phase 5 is considered bootstrapped.

## Steps

Create `tests/test_fsi_calculator.py`:

```python
import pytest
pytestmark = pytest.mark.unit

from utils.fsi_calculator import calculate_fsi, recommend_unit_mix, _ZONE_RULES


class TestCalculateFSI:
    def test_r2_basic(self):
        r = calculate_fsi(10000, "R2")
        assert r.far == 2.50
        assert r.buildable_area_sqft == pytest.approx(25000.0)
        assert r.sellable_area_sqft  == pytest.approx(16250.0)

    def test_r1_basic(self):
        r = calculate_fsi(10000, "R1")
        assert r.far == 1.75
        assert r.buildable_area_sqft == pytest.approx(17500.0)

    def test_c1_basic(self):
        r = calculate_fsi(10000, "C1")
        assert r.far == 2.25

    def test_zero_land_area(self):
        r = calculate_fsi(0, "R2")
        assert r.buildable_area_sqft == 0.0
        assert r.sellable_area_sqft  == 0.0

    def test_negative_land_area_clamped(self):
        r = calculate_fsi(-5000, "R2")
        assert r.buildable_area_sqft == 0.0

    def test_unknown_zone_defaults_to_r2(self):
        r = calculate_fsi(10000, "UNKNOWN")
        assert r.far == _ZONE_RULES["R2"]["far"]

    def test_efficiency_respected(self):
        r = calculate_fsi(10000, "R2", efficiency=0.70)
        assert r.sellable_area_sqft == pytest.approx(10000 * 2.5 * 0.70)

    def test_efficiency_clamped_max(self):
        r = calculate_fsi(10000, "R2", efficiency=2.0)
        assert r.sellable_area_sqft <= r.buildable_area_sqft

    def test_max_floors_positive(self):
        r = calculate_fsi(10000, "R2")
        assert r.max_floors >= 1

    def test_setbacks_returned(self):
        r = calculate_fsi(10000, "R1")
        assert r.setback_front_m == 3.0
        assert r.setback_side_m  == 1.5


class TestRecommendUnitMix:
    def test_affordable_psf(self):
        m = recommend_unit_mix(3500)
        assert m.psf_band == "affordable"
        assert m.bhk_2_pct > m.bhk_3_pct

    def test_mid_range_psf(self):
        m = recommend_unit_mix(6000)
        assert m.psf_band == "mid-range"

    def test_premium_psf(self):
        m = recommend_unit_mix(8500)
        assert m.psf_band == "premium"
        assert m.bhk_3_pct >= m.bhk_1_pct

    def test_unit_mix_sums_100(self):
        for psf in [3000, 5500, 9000]:
            m = recommend_unit_mix(psf)
            assert m.bhk_1_pct + m.bhk_2_pct + m.bhk_3_pct == 100

    def test_carpet_sqft_positive(self):
        m = recommend_unit_mix(6000)
        assert m.recommended_avg_carpet_sqft > 0
```

That is 15 tests — exceeds GATE-11 threshold of 12.

## Done When
- `tests/test_fsi_calculator.py` created with ≥12 tests
- All tests pass: `pytest tests/test_fsi_calculator.py -q`
- `ruff check .` passes
- GATE-11 marked PASSED in TASK_QUEUE.md
- CHANGELOG prepended

---

# T-363 — Wire Architect into Board Room Engineering Head

**Priority:** P2 | **Phase:** 5 Bootstrap | **Depends on:** T-361

## Why

The Board Room Engineering Head currently responds from pure LLM knowledge. If the pitch mentions a land area and/or market, the Engineering Head should auto-call the FSI calculator and include the result in its response — making the Board Room output quantitatively grounded, not just narrative.

## Steps

1. In `_run_dept_heads` in `crews/board_room.py`, detect if `pitch` mentions a numeric land area (e.g., "5-acre", "3 acres", "10000 sqft"). If so, call `calculate_fsi()` and `recommend_unit_mix()` with sensible defaults (zone=R2, psf from known market data or 6000 default).

2. Prepend the FSI result to the engineering `dept_question` before passing to the Engineering Head agent:
```python
# Inside run_single_agent for key == "engineering":
fsi_context = ""
import re
area_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-\s*)?acre", pitch, re.I)
if area_match:
    from utils.fsi_calculator import calculate_fsi, recommend_unit_mix
    acres = float(area_match.group(1))
    sqft  = acres * 43560
    fsi_r = calculate_fsi(sqft, zone="R2")
    mix_r = recommend_unit_mix(6500)  # default mid-range until market psf available
    fsi_context = (
        f"\n\n[AUTO FSI CALC — {acres} acres / {sqft:,.0f} sqft, Zone R2]\n"
        f"Buildable: {fsi_r.buildable_area_sqft:,.0f} sqft | "
        f"Sellable: {fsi_r.sellable_area_sqft:,.0f} sqft | "
        f"Max floors: {fsi_r.max_floors} | "
        f"Unit mix: {mix_r.bhk_1_pct}% 1BHK / {mix_r.bhk_2_pct}% 2BHK / {mix_r.bhk_3_pct}% 3BHK\n"
    )
dept_question = dept_question + fsi_context
```

3. **`py_compile crews/board_room.py`** + **`ruff check .`** must pass.

## Done When
- Pitch with "5-acre" triggers FSI calc in Engineering Head context
- FSI numbers appear in Engineering Head task description (visible in verbose logs)
- `ruff check .` passes
- CHANGELOG prepended

---

# T-364 — VISION.md Phase 2 + Phase 3: mark COMPLETE

**Priority:** P2 | **Depends on:** T-356 (GATE-10 passed)

## Why

Documentation is part of the definition of done. VISION.md is the master plan — if it says Phase 3 is still in progress after GATE-10 passes, every future session starts with a misleading picture.

## Steps

1. In `VISION.md`:
   - Phase 2 status: `🟡 IN PROGRESS` → `✅ COMPLETE — 2026-05-30`
   - Phase 2: tick all task checkboxes that are done
   - Phase 3 status: `🟡 BOOTSTRAP IN PROGRESS` → `✅ COMPLETE — 2026-05-30`
   - Phase 3 DoD note: update "4 department heads" to 5 (Legal added T-347)
   - Phase 3: tick all task checkboxes
   - "What Exists Today" table: update Board Room and Dashboard entries to ✅
   - Phase 5 status: `Not started` → `🟡 IN PROGRESS — bootstrap started (T-359, T-360, T-361)`
   - `CLAUDE.md` (root RE_OS): update Phase status lines at the top

## Done When
- Phase 2 and Phase 3 show ✅ COMPLETE in VISION.md
- Phase 5 shows 🟡 IN PROGRESS
- What Exists Today table updated
- CLAUDE.md phase status lines updated
- CHANGELOG prepended

---

# T-365 — DEVLOG.md Phase 2 + Phase 3 completion entries

**Priority:** P2 | **Depends on:** T-364

## Why

DEVLOG.md is the build history. Each phase completion should have an entry recording what was built, what gates were passed, and when.

## Steps

Add two entries to `DEVLOG.md` (prepend at the top after the header):

```markdown
## Phase 3 — Board Room Mode ✅ COMPLETE — 2026-05-30

**What was built:**
- crews/board_room.py — full 5-dept parallel Board Room (BD/Finance/Engineering/Ops/Legal)
- CEO pitch decomposition → 5 dept-specific sub-questions
- ThreadPoolExecutor with 90s timeout guard
- Action item extraction (Cerebras 8b) → structured action list
- Action approval UI — approve creates queued task in tasks table
- Board Room session history (GET /api/board/sessions)
- Legal Head agent (T-347) — RERA/BDA/title compliance lens
- Feasibility micro-tool (T-348) — LandFeasibility dataclass with GO/MARGINAL/NO-GO verdict
- DB: board_sessions table + legal_response column (Alembic 0006+0007)
- DB: tasks table (Alembic 0008)

**Gates passed:** GATE-10 (Phase 3 DoD)

---

## Phase 2 — Mission Control Dashboard ✅ COMPLETE — 2026-05-30

**What was built:**
- Flask dashboard at :8050 — 10 panels: Org Chart, Intel Board, Scout Feed, Task Board,
  Log Stream, Board Room, Sentinel, Pipeline Control, DB Explorer, Live Feed
- /api/health, /api/agents, /api/db/state, /api/intel/cards, /api/sentinel/status — all live
- /api/tasks CRUD (T-353)
- SSE log stream with per-market selector
- Pipeline Control panel — start/stop runs from UI
- DB Explorer — 3 sortable views (Market Inventory, Developer Scorecard, Active Projects)
- Board Room panel — pitch + 5-column response + action approval

**Gates passed:** GATE-2 (all 5 endpoints), GATE-8 (security), GATE-9 (prod readiness)
```

## Done When
- Two phase entries added to DEVLOG.md
- CHANGELOG prepended

---

# T-281 — RERA Scraper: Fix Yelahanka + Hebbal Locality Selectors

**Assigned:** Kilo Code | **Priority:** P0 | **Gate:** GATE-4

## Why

Yelahanka and Hebbal return 8 hardcoded fallback projects instead of live RERA data. Devanahalli works (317 projects from `Bengaluru Rural` district). The RERA portal uses a POST-based DataTables search. The scraper sends a locality string but the portal doesn't recognise it, so it returns the global fallback.

Current state (`scrapers/rera_karnataka.py`): `ALT_SUBDISTRICTS` retry loop already exists — Hebbal tries `Bangalore North`, Yelahanka tries `Bengaluru North`. These still return 0. The raw HTML is logged at WARNING on failure.

## Steps

1. **Reproduce the failure first.** Run a standalone scrape inside Docker and read the raw HTML warning:
   ```bash
   docker compose exec agents python scrapers/rera_karnataka.py --market Yelahanka
   ```
   Find the line `[RERA] Raw HTML logged` in the output. Read the actual HTML to see what field names and option values the portal expects.

2. **Find the correct subdistrict value.** The RERA Karnataka portal (`rera.karnataka.gov.in`) has a locality/subdistrict dropdown. Inspect the network POST payload from a working Devanahalli request to understand the exact field structure. Compare with Yelahanka — the field name may be `taluk`, `locality`, or `subDistrict`. Check `ALT_SUBDISTRICTS` values against the dropdown options visible in the raw HTML.

3. **Update `ALT_SUBDISTRICTS`** in `scrapers/rera_karnataka.py` with the correct values found in step 2. If the field name itself is wrong, fix the POST payload builder too.

4. **Run a live validation:**
   ```bash
   docker compose exec agents python scrapers/rera_karnataka.py --market Yelahanka
   docker compose exec agents python scrapers/rera_karnataka.py --market Hebbal
   ```
   Log the result count.

5. **If the portal is still unreachable** (HTTP 403/timeout, not a selector issue): document the exact HTTP response code, headers, and what was tried in CHANGELOG.md. Do not mark DONE — mark BLOCKED with the finding.

## Done When

- [ ] Yelahanka OR Hebbal returns ≥ 50 live RERA projects (not fallback)
- [ ] The scrape checkpoint file is written with `data_source: portal_scraped` (not `seed_estimated`)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written with exact result counts

---

---

# T-302 — Test Coverage: DBOrganizer

**Assigned:** Cline | **Priority:** P1 | **Gate:** GATE-7

## Why

`DBOrganizer` is the most critical non-LLM component in the pipeline — all RERA, portal, kaveri, developer, and news data flows through it. It currently has zero test coverage. One bad change here corrupts the data layer silently.

## Steps

1. Create `tests/test_db_organizer.py`.

2. Use the real PostgreSQL test DB (DATABASE_URL from env, same as other integration tests). All three tests require the DB to be up — skip gracefully if `DATABASE_URL` is not set:
   ```python
   import pytest, os
   pytestmark = pytest.mark.skipif(
       not os.environ.get("DATABASE_URL"), reason="requires live DB"
   )
   ```

3. **Test 1 — insert then update:**
   - Build 2 valid RERA project dicts with unique `rera_number` values (use `RERA-TEST-001`, `RERA-TEST-002`). Market = `Yelahanka` (already seeded in micro_markets).
   - Call `DBOrganizer().run("Yelahanka", [r1, r2])`.
   - Assert `stats["inserted"] == 2`, `stats["failed"] == 0`.
   - Call `run()` again with identical records.
   - Assert `stats["updated"] == 2`, `stats["inserted"] == 0`.

4. **Test 2 — missing required field is skipped:**
   - Build a record with no `project_name` key.
   - Assert `stats["failed"] == 1` and no exception raised.

5. **Test 3 — SAVEPOINT rollback: bad record doesn't block good ones:**
   - Batch of 3: record 1 valid, record 2 has a malformed `rera_number` that violates the UNIQUE constraint (insert it twice in the batch), record 3 valid.
   - Assert `stats["inserted"] >= 2` (records 1 and 3 inserted), `stats["failed"] >= 1`.

6. **Cleanup:** each test must clean up inserted rows:
   ```python
   conn.execute(text("DELETE FROM rera_projects WHERE rera_number LIKE 'RERA-TEST-%'"))
   ```
   Use a pytest fixture with `yield` + cleanup.

7. Run: `pytest tests/test_db_organizer.py -v`

## Done When

- [ ] `pytest tests/test_db_organizer.py` passes (3 tests, no errors)
- [ ] Test file correctly skips when DATABASE_URL is not set (CI-safe)
- [ ] Coverage report shows `utils/db_organizer.py` coverage improved
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-315 — Board Room: Stuck Session Recovery

**Assigned:** Kilo Code | **Priority:** P1

## Why

`run_board_session()` starts a daemon thread to run dept-head agents. If the gunicorn worker is restarted mid-run (OOM, timeout, deploy), the thread dies but the DB row stays at `status = 'active'` forever. There is no recovery. Sessions pile up as false-actives, confusing the dashboard.

## Steps

1. Open `config/scheduler.py`. Add a new APScheduler job that runs every hour:
   ```python
   def recover_stuck_board_sessions():
       """Set board sessions stuck at 'active' for >30 minutes to 'failed'."""
   ```

2. Inside the function:
   - Get a DB connection via `create_engine(DATABASE_URL).connect()`
   - Execute:
     ```sql
     UPDATE board_sessions
     SET status = 'failed',
         completed_at = NOW()
     WHERE status = 'active'
       AND created_at < NOW() - INTERVAL '30 minutes'
     ```
   - Log: `logger.info(f"[Scheduler] Recovered {rowcount} stuck board sessions")`
   - Close connection.

3. Register the job in the scheduler startup block:
   ```python
   scheduler.add_job(
       recover_stuck_board_sessions,
       "interval", hours=1,
       id="recover_board_sessions",
       replace_existing=True,
   )
   ```

4. Wrap the entire function body in `try/except Exception as e: logger.warning(...)` — this job must be non-fatal.

5. Verify the job appears in `scheduler.get_jobs()` output at startup.

## Done When

- [ ] `config/scheduler.py` has the new job registered
- [ ] Scheduler starts without error (`docker compose up scheduler` logs show the job ID)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-316 — Dockerfile: Remove Duplicate Chromium Install

**Assigned:** Kilo Code | **Priority:** P1

## Why

`Dockerfile` installs Chromium twice: once via `apt-get install chromium chromium-driver` (~200MB) and once via `playwright install chromium` (Playwright-managed binary at `/ms-playwright`). The scrapers use Playwright's binary exclusively — the apt install is dead weight that inflates every image build and every container pull.

## Steps

1. Open `Dockerfile`.

2. Remove `chromium` and `chromium-driver` from the `apt-get install` line. Keep `gcc`, `libpq-dev`, `curl`.

3. `CHROME_BIN` and `CHROMEDRIVER_PATH` env vars point to the apt paths. Remove both env vars — Playwright does not need them and they would point to non-existent binaries after the removal.

4. Verify the build compiles:
   ```bash
   docker build . --tag re_os:test --no-cache
   ```
   The build must succeed. Playwright's own Chromium install (`playwright install chromium`) remains and is the active browser.

5. Verify scrapers still work by running a quick standalone scrape:
   ```bash
   docker compose run --rm agents python scrapers/rera_karnataka.py --market Devanahalli
   ```
   Devanahalli has live RERA data — expect 317 projects or similar.

## Done When

- [ ] `docker build` succeeds without errors
- [ ] `chromium` and `chromium-driver` no longer appear in `apt-get install`
- [ ] `CHROME_BIN` and `CHROMEDRIVER_PATH` removed from Dockerfile
- [ ] Devanahalli scrape returns live projects (not 0 or error)
- [ ] CHANGELOG.md entry written with image size before/after (run `docker images re_os:test` to get size)

---

---

# T-317 — Dashboard: Delete Deprecated `/api/intel` Endpoint

**Assigned:** Cline | **Priority:** P1

## Why

`GET /api/intel` reads intel report files from disk and returns up to 500 chars of content. `GET /api/intel/cards` does the same job properly via a DB query with richer output. The file-read endpoint is slower, redundant, and the dashboard JS now uses `/api/intel/cards` exclusively. Dead endpoints are security surface area.

## Steps

1. Open `dashboard/app.py`.

2. Confirm the dashboard UI (`dashboard/templates/index.html`) does not call `/api/intel` anywhere:
   ```bash
   grep -n "api/intel\"" dashboard/templates/index.html
   ```
   Expected: only `/api/intel/cards` and `/api/intel/download` — no bare `/api/intel`.

3. Delete the `get_intel()` function and its `@app.route("/api/intel")` decorator entirely from `app.py`.

4. Verify the app starts: `python -m py_compile dashboard/app.py` → exit 0.

5. Verify the remaining intel routes still work:
   - `GET /api/intel/cards` — still present
   - `GET /api/intel/download` — still present
   - `GET /api/intel` — should now return 404

## Done When

- [ ] `get_intel()` function deleted from `dashboard/app.py`
- [ ] `GET /api/intel` returns 404
- [ ] `GET /api/intel/cards` and `/api/intel/download` return 200
- [ ] No references to `/api/intel` remain in `index.html` (grep confirms)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-318 — Board Room Engine Pool: Increase to pool_size=5

**Assigned:** Cline | **Priority:** P1

## Why

`crews/board_room.py` `_get_engine()` creates the SQLAlchemy engine with `pool_size=2, max_overflow=0`. A board session runs 4 concurrent dept-head threads plus the main thread — all may need DB connections simultaneously. Pool exhaustion causes `TimeoutError` and a failed session under any real load.

## Steps

1. Open `crews/board_room.py`.

2. Find `_get_engine()`. Change the `create_engine` call:
   ```python
   # Before
   _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=0)
   # After
   _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=2)
   ```

3. That is the entire change. Do not touch anything else in this function.

4. Verify syntax: `python -m py_compile crews/board_room.py` → exit 0.

## Done When

- [ ] `pool_size=5, max_overflow=2` in `_get_engine()`
- [ ] `python -m py_compile crews/board_room.py` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-319 — Dashboard: CORS Headers with Origin Allowlist

**Assigned:** Kilo Code | **Priority:** P2

## Why

The Flask dashboard has no CORS configuration. Any attempt to access it from a different origin (nginx reverse proxy, different port, Obsidian web view) will be silently blocked by the browser. This becomes a blocker the moment anything other than the direct container port is used.

## Steps

1. Add `flask-cors>=4.0.0` to `requirements.txt` under the Dashboard section.

2. Open `dashboard/app.py`. After the `app = Flask(...)` line, add:
   ```python
   from flask_cors import CORS
   _ALLOWED_ORIGINS = [
       o.strip()
       for o in os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "http://localhost:8050").split(",")
       if o.strip()
   ]
   CORS(app, origins=_ALLOWED_ORIGINS)
   ```

3. Add `DASHBOARD_ALLOWED_ORIGINS` to the agents service env block in `docker-compose.yml`:
   ```yaml
   DASHBOARD_ALLOWED_ORIGINS: ${DASHBOARD_ALLOWED_ORIGINS:-http://localhost:8050}
   ```

4. Add `DASHBOARD_ALLOWED_ORIGINS=http://localhost:8050` to `.env.example` with a comment explaining it accepts comma-separated origins.

5. Verify the app starts: `python -m py_compile dashboard/app.py` → exit 0.

## Done When

- [ ] `flask-cors` in `requirements.txt`
- [ ] CORS applied in `app.py` using env-var allowlist
- [ ] `DASHBOARD_ALLOWED_ORIGINS` in docker-compose.yml agents env + `.env.example`
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-320 — `_log_event`: Structured JSON Serialisation

**Assigned:** Kilo Code | **Priority:** P2

## Why

`_log_event()` in `crews/market_intel_crew.py` calls `logger.info(payload)` where `payload` is a Python dict. The loguru text sink stringifies it as `{'key': 'val'}` — not valid JSON, not grep-friendly. Every pipeline event is unreadable in log analysis.

## Steps

1. Open `crews/market_intel_crew.py`. Find `_log_event()`.

2. Change the last line from:
   ```python
   logger.info(payload)
   ```
   to:
   ```python
   logger.info("pipeline_event | {}", json.dumps(payload))
   ```

3. `json` is already imported at module level — no new import needed.

4. Verify: `python -m py_compile crews/market_intel_crew.py` → exit 0.

## Done When

- [ ] `logger.info(payload)` replaced with `logger.info("pipeline_event | {}", json.dumps(payload))`
- [ ] `python -m py_compile crews/market_intel_crew.py` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-321 — Replace `_daily_counts` Direct Import

**Assigned:** Cline | **Priority:** P2

## Why

`crews/market_intel_crew.py` imports `_daily_counts` directly from `config.llm_router`:
```python
from config.llm_router import _exclude, _clear_excluded, _is_excluded, _daily_counts
```
`_daily_counts` is a live mutable dict. Iterating it (`logger.info(f"... {_daily_counts}")`) while another thread is writing to it can raise `RuntimeError: dictionary changed size during iteration`.

The correct approach is to call `get_router_status()` which returns a safe snapshot.

## Steps

1. Open `crews/market_intel_crew.py`.

2. Remove `_daily_counts` from the import line:
   ```python
   # Before
   from config.llm_router import _exclude, _clear_excluded, _is_excluded, _daily_counts
   # After
   from config.llm_router import _exclude, _clear_excluded, _is_excluded, get_router_status
   ```

3. Find the two places in the file where `_daily_counts` is logged:
   ```python
   logger.info(f"[Router] Daily counts: {_daily_counts}")
   ```
   Replace both with:
   ```python
   logger.info("[Router] Daily counts: {}", get_router_status().get("excluded", "n/a"))
   ```

4. Verify: `python -m py_compile crews/market_intel_crew.py` → exit 0.

## Done When

- [ ] `_daily_counts` removed from import
- [ ] Both log call sites updated to use `get_router_status()`
- [ ] `python -m py_compile crews/market_intel_crew.py` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-322 — Remove Unused `superseded_by` FK from `agent_memories`

**Assigned:** Cline | **Priority:** P2

## Why

`agent_memories.superseded_by UUID REFERENCES agent_memories(memory_id)` exists in `schema.sql` and in the Alembic migration but is never set by any code path. It is dead schema — it adds FK overhead, confuses future readers, and implies a feature that does not exist.

## Steps

1. **Alembic migration (new file):** Create `alembic/versions/0005_drop_superseded_by.py`:
   ```python
   """drop unused superseded_by column from agent_memories"""
   revision = "0005_drop_superseded_by"
   down_revision = "0004_..."  # check latest revision in alembic/versions/
   
   from alembic import op
   
   def upgrade():
       op.drop_column("agent_memories", "superseded_by")
   
   def downgrade():
       op.add_column(
           "agent_memories",
           sa.Column("superseded_by", sa.UUID(), nullable=True),
       )
   ```
   Fill in `down_revision` by checking what the current head migration ID is in `alembic/versions/`.

2. **Remove from `schema.sql`**: Delete the `superseded_by UUID REFERENCES agent_memories(memory_id),` line from the `CREATE TABLE IF NOT EXISTS agent_memories` block.

3. **Remove from `models.py`** if present: delete the `superseded_by` column definition from the `AgentMemory` ORM model.

4. Do NOT apply the migration to the live DB — that is done via `alembic upgrade head` on next restart (T-324 handles this).

5. Verify: `python -m py_compile alembic/versions/0005_drop_superseded_by.py` → exit 0.

## Done When

- [ ] Migration file created with correct `down_revision`
- [ ] `superseded_by` removed from `schema.sql`
- [ ] `superseded_by` removed from `models.py` (if present)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-323 — `v_developer_scorecard`: Deterministic `STRING_AGG`

**Assigned:** Kilo Code | **Priority:** P2

## Why

`v_developer_scorecard` uses `STRING_AGG(DISTINCT mm.name, ', ')` with no `ORDER BY` clause. PostgreSQL does not guarantee ordering for `DISTINCT` aggregates without an explicit `ORDER BY`. Output varies across query plans and PostgreSQL versions — makes test assertions on this field brittle.

## Steps

1. Open `database/schema.sql`. Find `v_developer_scorecard`.

2. Change:
   ```sql
   STRING_AGG(DISTINCT mm.name, ', ') AS markets_active_in
   ```
   to:
   ```sql
   STRING_AGG(DISTINCT mm.name, ', ' ORDER BY mm.name) AS markets_active_in
   ```

3. Apply the same fix to any Alembic migration that recreates this view. Search:
   ```bash
   grep -r "STRING_AGG" alembic/
   ```
   Update any matches.

4. The view is `CREATE VIEW` not `CREATE TABLE` — no migration needed for the schema change itself (views are recreated on DB init). But if a migration creates or replaces the view, update it there too.

## Done When

- [ ] `ORDER BY mm.name` added inside `STRING_AGG(DISTINCT ...)` in `schema.sql`
- [ ] All Alembic migration copies of this view updated (if any)
- [ ] `ruff check .` passes (SQL files are not checked by ruff, but Python migration files are)
- [ ] CHANGELOG.md entry written

---

---

# T-324 — Alembic Upgrade on Container Startup

**Assigned:** Kilo Code | **Priority:** P2

## Why

`schema.sql` initialises a fresh DB but Alembic migrations (T-322's new `0005_drop_superseded_by` and others) are never applied automatically. Each time a new migration is added, it only runs if someone manually runs `alembic upgrade head`. This is a production reliability gap — deploys silently run on stale schema.

## Steps

1. Open `docker-compose.yml`. Find the `agents` service `command` block:
   ```yaml
   command: >
     gunicorn dashboard.app:app ...
   ```

2. Change it to run alembic first, then gunicorn:
   ```yaml
   command: >
     sh -c "alembic upgrade head &&
            gunicorn dashboard.app:app
            --bind 0.0.0.0:8050
            --workers 1
            --threads 8
            --timeout 120
            --access-logfile -
            --error-logfile -"
   ```

3. `alembic` is already in `requirements.txt`. The `alembic.ini` and `env.py` exist and read `DATABASE_URL` from the environment.

4. **Critical:** `alembic upgrade head` must complete before gunicorn starts. The `sh -c "... && ..."` pattern enforces this — if alembic fails, gunicorn does not start (fail fast).

5. Verify the change parses correctly:
   ```bash
   docker compose config --quiet
   ```

6. Do NOT change the scheduler command — it does not serve the DB-backed API.

## Done When

- [ ] `alembic upgrade head` runs before gunicorn in agents service command
- [ ] `docker compose config --quiet` passes (no YAML parse error)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written
- [ ] Note: full verification (container start + alembic log output) happens on next `docker compose up`

---

---

# T-325 — CI: Add pip-audit for CVE Scanning

**Assigned:** Kilo Code | **Priority:** P1 | **Gate:** GATE-8

## Why

The CI pipeline (`.github/workflows/ci.yml`) runs py_compile, ruff, and pytest but has no CVE scan. Any dependency with a known vulnerability ships silently. pip-audit checks installed packages against PyPI advisory database in seconds — it's a pure CI addition with zero runtime footprint.

## Steps

1. Open `.github/workflows/ci.yml`. Find the `steps:` block in the main job.

2. After the `pip install -r requirements.txt` step and before the `ruff check .` step, add:
   ```yaml
   - name: pip-audit (CVE scan)
     run: pip install pip-audit && pip-audit --requirement requirements.txt --ignore-vuln PYSEC-2022-42969
   ```
   The `--ignore-vuln` flag is a safety valve for known false-positives. Start without it — only add it if a specific advisory fires that is documented as a false positive.

3. Simpler version if the above is too verbose for the workflow style — just add `pip-audit` to the install step and run it:
   ```yaml
   - name: pip-audit (CVE scan)
     run: pip-audit -r requirements.txt
   ```

4. Verify the YAML parses cleanly — copy the CI file to a temp location and run:
   ```bash
   python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
   ```

5. Do NOT add pip-audit to `requirements.txt` — it is a dev/CI-only tool, not a runtime dependency. Install it inline in the workflow step only.

## Done When

- [ ] `pip-audit -r requirements.txt` step present in `.github/workflows/ci.yml`
- [ ] YAML parses without error (`python -c "import yaml..."`)
- [ ] `ruff check .` passes (Python files, not YAML)
- [ ] CHANGELOG.md entry written

---

---

# T-326 — Makefile: Add `make ci` Target

**Assigned:** Kilo Code | **Priority:** P2 | **Gate:** GATE-8

## Why

`make format` exists but there is no `make ci` — the only way to replicate CI locally is to manually run three commands in sequence. Every developer touching this project pays this tax. A `make ci` target that mirrors the CI steps exactly eliminates the gap and removes the excuse not to run checks before pushing.

## Steps

1. Open `Makefile` (project root). Find the existing `format` and any other targets.

2. Add the following targets below the existing ones:

   ```makefile
   .PHONY: ci lint test

   lint:
   	ruff check .
   	ruff format --check .

   test:
   	pytest tests/ -q

   ci: lint test
   	@echo "CI checks passed"
   ```

3. The `ci` target chains `lint` then `test`. If either fails, `make ci` exits non-zero — same semantics as the GitHub Actions workflow.

4. Do NOT add `pip-audit` to this target — pip-audit is CI-only (not installed locally unless explicitly set up). Keeping `make ci` to ruff + pytest makes it zero-friction for local use.

5. Verify the Makefile parses:
   ```bash
   make ci --dry-run
   ```
   Expected: prints the commands it would run, exits 0.

## Done When

- [ ] `make ci` runs `ruff check . && ruff format --check . && pytest tests/ -q`
- [ ] `make lint` and `make test` exist as standalone targets
- [ ] `make ci --dry-run` exits 0
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-327 — Fix SQLAlchemy Pool Size in agent_memory.py + market_intel_crew.py

**Assigned:** Kilo Code | **Priority:** P2

## Why

Three files create SQLAlchemy engines. `db_organizer.py` was fixed to `pool_size=5, max_overflow=2` (R21). The other two were not:

- `utils/agent_memory.py` line ~34: `pool_size=2, max_overflow=0`
- `crews/market_intel_crew.py` line ~114: `pool_size=2, max_overflow=0`

`market_intel_crew.py` runs the 3-stage pipeline. During Stage 3, the CEO agent, Analyst agent, and the organizer engine all compete for DB connections. Pool of 2 with no overflow means the third concurrent access blocks until one releases — adds latency and risks TimeoutError on slow DB operations. `agent_memory` is read + written during every scraper iteration — pool of 2 is a bottleneck under parallel market runs.

## Steps

1. Open `utils/agent_memory.py`. Find the line:
   ```python
   _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=0)
   ```
   Change to:
   ```python
   _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=2)
   ```

2. Open `crews/market_intel_crew.py`. Find the equivalent `create_engine` call (around line 114). Apply the same change: `pool_size=5, max_overflow=2`.

3. Verify both files compile:
   ```bash
   python -m py_compile utils/agent_memory.py
   python -m py_compile crews/market_intel_crew.py
   ```

4. Run tests to confirm nothing broke:
   ```bash
   pytest tests/ -q
   ```

## Done When

- [ ] `utils/agent_memory.py` has `pool_size=5, max_overflow=2`
- [ ] `crews/market_intel_crew.py` has `pool_size=5, max_overflow=2`
- [ ] Both `py_compile` checks pass
- [ ] `pytest tests/ -q` exits 0
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written (one entry, both files)

---

---

# T-328 — Dashboard Route Tests: Smoke Coverage for 5 Key Endpoints

**Assigned:** Cline | **Priority:** P1 | **Gate:** GATE-8

## Why

The auth fix (before_request) and rate limiting added in R21 have zero test coverage. A regression that re-opens the pipeline trigger to unauthenticated requests would ship silently. This is the "security fix untested" finding from the May-19 audit.

## Steps

1. Create `tests/test_dashboard_routes.py`.

2. Use Flask's test client — no real DB or Docker needed:
   ```python
   import pytest
   import sys, os
   sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

   @pytest.fixture
   def client():
       from dashboard.app import app
       app.config["TESTING"] = True
       with app.test_client() as c:
           yield c
   ```

3. **Test 1 — /api/health returns 200 without auth key:**
   ```python
   def test_health_no_auth(client):
       r = client.get("/api/health")
       assert r.status_code == 200
   ```

4. **Test 2 — /api/run/<market> returns 401 without key when DASHBOARD_API_KEY is set:**
   ```python
   def test_run_trigger_requires_auth(client, monkeypatch):
       monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
       r = client.post("/api/run/yelahanka")
       assert r.status_code == 401
   ```

5. **Test 3 — /api/run/<market> returns 200-level (not 401) with correct key:**
   ```python
   def test_run_trigger_with_auth(client, monkeypatch):
       monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
       r = client.post("/api/run/yelahanka", headers={"X-API-Key": "secret"})
       assert r.status_code in (200, 202, 409)  # running/accepted/already running
   ```

6. **Test 4 — /api/db/state returns 200 without auth (read-only):**
   ```python
   def test_db_state_no_auth(client):
       r = client.get("/api/db/state")
       assert r.status_code in (200, 500)  # 500 ok if DB not running in CI
   ```

7. **Test 5 — /api/run with invalid market returns 400:**
   ```python
   def test_run_invalid_market(client, monkeypatch):
       monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
       r = client.post("/api/run/fakecity", headers={"X-API-Key": "secret"})
       assert r.status_code == 400
   ```

8. Run: `pytest tests/test_dashboard_routes.py -v`

**Note:** Tests 3 and 5 may start a subprocess — confirm the route's MARKET_CANONICAL check fires before any Popen call. If it does (it should), no real pipeline runs in tests.

## Done When

- [ ] `pytest tests/test_dashboard_routes.py` passes all 5 tests
- [ ] Test 2 confirms 401 when key is set but not provided
- [ ] Test 3 confirms auth gates pass correctly
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-329 — db_organizer: Validate data_source Against Allowed Values

**Assigned:** Cline | **Priority:** P2

## Why

The `rera_projects` table has a `data_source` CHECK constraint allowing only `{'portal_scraped', 'seed_estimated', 'api_fetched'}`. The organizer writes this field from scraper output without validating it first. A scraper returning an unexpected string (e.g. `"playwright_timeout"` or `"unknown"`) causes a silent SAVEPOINT rollback — the record is dropped with no error propagation to the operator.

## Steps

1. Open `utils/db_organizer.py`. Find `_upsert_rera_project()` (or equivalent upsert method for RERA records).

2. At the top of the method, before the INSERT, add validation:
   ```python
   VALID_DATA_SOURCES = {"portal_scraped", "seed_estimated", "api_fetched"}
   data_source = record.get("data_source", "seed_estimated")
   if data_source not in VALID_DATA_SOURCES:
       logger.warning(
           f"[Organizer] Invalid data_source '{data_source}' — defaulting to 'seed_estimated'"
       )
       data_source = "seed_estimated"
   ```

3. Use the validated `data_source` local variable (not `record["data_source"]`) in the INSERT statement.

4. Add a corresponding test case in `tests/test_db_organizer.py` (which T-302 creates):
   - Build a record with `data_source = "playwright_timeout"` — an invalid value.
   - After `DBOrganizer().run(...)`, the record should be inserted with `data_source = 'seed_estimated'`.
   - Query the row to confirm.

   If T-302 is not yet done, add a standalone test function in a new file `tests/test_db_organizer_validation.py` with the same DB-skip guard.

5. Run: `pytest tests/ -q`

## Done When

- [ ] `data_source` validated against `VALID_DATA_SOURCES` before INSERT
- [ ] Invalid values log a warning and fall back to `seed_estimated`
- [ ] Test confirms fallback behaviour
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-330 — Remove Dead sys.path.append() Calls Across All Modules

**Assigned:** Kilo Code | **Priority:** P1

## Why

`PYTHONPATH: /app` was added to both `agents` and `scheduler` services in docker-compose.yml (R21). Every `sys.path.append(os.path.dirname(...))` call in the codebase is now dead code that silently does nothing inside containers. It adds noise, misleads readers into thinking path manipulation is needed, and remains as a landmine if PYTHONPATH is ever mis-set.

Affected files (13):
- `crews/market_intel_crew.py`
- `config/llm_router.py`
- `config/scheduler.py`
- `config/run_logger.py`
- `scrapers/kaveri_karnataka.py`
- `scrapers/rera_karnataka.py`
- `scrapers/developer_scout.py`
- `scrapers/rera_detail_scout.py`
- `scrapers/portal_scout.py`
- `scrapers/news_scout.py`
- `scrapers/listings_scraper.py`
- `agents/scraper_agent.py`
- `agents/analyst_agent.py`
- `agents/parser_agent.py`
- `agents/ceo_agent.py`
- `utils/db_organizer.py`

## Steps

1. Grep to confirm the full list of affected files:
   ```bash
   grep -rn "sys.path.append" . --include="*.py" | grep -v "__pycache__"
   ```

2. For each file: remove the `import sys`, `import os` (only if they are used solely for the path append — check other uses first), and the `sys.path.append(...)` line.

   **Critical:** `import os` and `import sys` are often used elsewhere in the same file. Only remove the import if the ENTIRE file has no other use of `sys` or `os`. If in doubt, keep the import and only remove the `sys.path.append(...)` call.

3. For standalone scripts (files with `if __name__ == "__main__":` blocks that run directly outside Docker), keep the sys.path.append — those scripts may be run from host without PYTHONPATH set. Check each file's `__main__` block.

   Rule: if the file is **only** run inside the container (crews, agents, scrapers invoked via `docker compose exec`), remove. If it has a standalone run mode used from the host, keep with a comment explaining why.

4. After all removals, run:
   ```bash
   python -m py_compile crews/market_intel_crew.py
   python -m py_compile config/llm_router.py
   python -m py_compile config/scheduler.py
   ```
   And for each modified file.

5. Run the test suite:
   ```bash
   pytest tests/ -q
   ```

## Done When

- [ ] All `sys.path.append(os.path.dirname(...))` calls removed from container-only files
- [ ] `import sys` / `import os` removed only where they had no other use
- [ ] All modified files pass `py_compile`
- [ ] `pytest tests/ -q` exits 0
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written listing the files changed

---

---

# T-331 — Fix Scheduler Engine Leak: Module-Level Singleton for DB Connections

**Assigned:** Kilo Code | **Priority:** P1

## Why

`config/scheduler.py` creates a **fresh `create_engine()` call inside each job function** — `run_market_snapshot()` at line ~104 and `recover_stuck_board_sessions()` at line ~164. Each job fires on a schedule: market snapshots daily, board session recovery every hour. Every call creates a new SQLAlchemy engine with its own connection pool, uses it once, and **never disposes it**. Connection pools accumulate in memory for the lifetime of the scheduler process — this is a classic resource leak.

Pattern in scheduler today:
```python
def run_market_snapshot():
    engine = create_engine(DATABASE_URL)  # new pool every call
    with engine.begin() as conn:
        ...  # engine never disposed
```

## Steps

1. Open `config/scheduler.py`. Add a module-level engine singleton after the imports:
   ```python
   from sqlalchemy import create_engine, text
   from config.settings import DATABASE_URL

   _scheduler_engine = None
   _scheduler_engine_lock = __import__("threading").Lock()

   def _get_scheduler_engine():
       global _scheduler_engine
       if _scheduler_engine is None:
           with _scheduler_engine_lock:
               if _scheduler_engine is None:
                   _scheduler_engine = create_engine(
                       DATABASE_URL,
                       pool_pre_ping=True,
                       pool_size=3,
                       max_overflow=1,
                   )
       return _scheduler_engine
   ```

2. Remove the inline `create_engine` calls from `run_market_snapshot()` and `recover_stuck_board_sessions()`. Replace with:
   ```python
   engine = _get_scheduler_engine()
   ```

3. The `with engine.begin() as conn:` pattern remains unchanged — it handles connection acquire/release. Only the engine creation changes.

4. Remove the local `from sqlalchemy import create_engine, text` inside the job functions — move them to the module-level import block if not already there.

5. Verify: `python -m py_compile config/scheduler.py` → exit 0.

## Done When

- [ ] Module-level `_get_scheduler_engine()` singleton added
- [ ] `run_market_snapshot()` uses `_get_scheduler_engine()` — no inline `create_engine`
- [ ] `recover_stuck_board_sessions()` uses `_get_scheduler_engine()` — no inline `create_engine`
- [ ] `ruff check .` passes
- [ ] `python -m py_compile config/scheduler.py` passes
- [ ] CHANGELOG.md entry written

---

---

# T-332 — Gunicorn: Add --max-requests Flags to Prevent Memory Bloat

**Assigned:** Kilo Code | **Priority:** P2

## Why

The agents container runs gunicorn with `--workers 1 --threads 8`. A single long-running worker process accumulates memory over time — each request imports, caches, and allocates objects that are never freed (Python's GC is generational, not real-time). Without `--max-requests`, the worker runs forever and memory grows unbounded. `--max-requests 500` restarts the worker after 500 requests; `--max-requests-jitter 50` adds randomness so restarts don't all hit at once during traffic spikes. The restart is graceful — in-flight requests finish before the worker cycles.

## Steps

1. Open `docker-compose.yml`. Find the agents service `command` block (which after T-324 starts with `alembic upgrade head &&`).

2. Add `--max-requests 500` and `--max-requests-jitter 50` to the gunicorn flags:
   ```yaml
   command: >
     sh -c "alembic upgrade head &&
            gunicorn dashboard.app:app
            --bind 0.0.0.0:8050
            --workers 1
            --threads 8
            --timeout 120
            --max-requests 500
            --max-requests-jitter 50
            --access-logfile -
            --error-logfile -"
   ```

   If T-324 is not yet done (alembic prefix not present), add to the existing gunicorn command line without the `sh -c` wrapper.

3. Verify YAML parses:
   ```bash
   docker compose config --quiet
   ```

## Done When

- [ ] `--max-requests 500 --max-requests-jitter 50` present in agents gunicorn command
- [ ] `docker compose config --quiet` passes
- [ ] CHANGELOG.md entry written

---

---

# T-333 — Flask after_request: Add HTTP Security Headers

**Assigned:** Kilo Code | **Priority:** P2

## Why

The dashboard exposes a Flask API at port 8050. Without security headers, browsers have no instructions on how to handle the response — content sniffing is enabled, the page can be framed by any origin, and referrer information leaks to third-party resources. These are OWASP-standard headers that take one `after_request` block to add and immediately improve the Security audit score.

## Steps

1. Open `dashboard/app.py`. After the `limiter = Limiter(...)` block, add:
   ```python
   @app.after_request
   def _add_security_headers(response):
       response.headers["X-Content-Type-Options"] = "nosniff"
       response.headers["X-Frame-Options"] = "DENY"
       response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
       response.headers["X-XSS-Protection"] = "0"  # modern browsers: disable legacy XSS filter
       return response
   ```

   Place this **before** the `before_request` function so it's easy to find alongside other request lifecycle hooks.

2. `X-XSS-Protection: 0` is intentional — the legacy XSS filter in old browsers can be exploited; modern security guidance is to disable it and rely on CSP instead.

3. Verify syntax: `python -m py_compile dashboard/app.py` → exit 0.

4. Quick smoke test — start the app locally or in Docker and check a response header:
   ```bash
   curl -I http://localhost:8050/api/health
   ```
   Expect `X-Content-Type-Options: nosniff` in the output.

## Done When

- [ ] `_add_security_headers` after_request hook added to `dashboard/app.py`
- [ ] All four headers present: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `X-XSS-Protection`
- [ ] `python -m py_compile dashboard/app.py` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-334 — Update .env.example with Keys Added Since Last Review

**Assigned:** Kilo Code | **Priority:** P2

## Why

`.env.example` is the deployment contract — a new operator copies it to `.env` and fills in keys. Two keys have been added since the last review that are missing from `.env.example`:
1. `DASHBOARD_ALLOWED_ORIGINS` — added by T-319 (Flask-CORS allowlist)
2. `DASHBOARD_API_KEY_PREV` — used in zero-downtime key rotation (T-250), already in docker-compose but not in `.env.example`

A missing key in `.env.example` means the first time anyone deploys, CORS silently fails or key rotation is undocumented.

## Steps

1. Open `.env.example`. Find the `DASHBOARD_API_KEY` line.

2. Add below it:
   ```bash
   # Zero-downtime key rotation: set OLD_KEY here while rotating to new DASHBOARD_API_KEY.
   # Both keys will be accepted simultaneously. Remove PREV once clients have migrated.
   DASHBOARD_API_KEY_PREV=

   # CORS allowlist for dashboard JS clients. Comma-separated origins.
   # Accepts: http://localhost:8050 (default), or your nginx/proxy origin.
   DASHBOARD_ALLOWED_ORIGINS=http://localhost:8050
   ```

3. Scan for any other env vars referenced in docker-compose.yml that are not in `.env.example`:
   ```bash
   grep -o '\${[A-Z_]*' docker-compose.yml | tr -d '${' | sort -u
   ```
   Cross-check against `.env.example` keys. Add any missing ones with a comment.

4. Verify `.env.example` is committed and `.env` is in `.gitignore`:
   ```bash
   grep "^\.env$" .gitignore
   ```

## Done When

- [ ] `DASHBOARD_API_KEY_PREV` added to `.env.example` with rotation instructions
- [ ] `DASHBOARD_ALLOWED_ORIGINS` added to `.env.example` with comment
- [ ] All docker-compose `${VAR}` references covered in `.env.example`
- [ ] `.env` confirmed in `.gitignore`
- [ ] CHANGELOG.md entry written

---

---

# T-335 — GitHub PR Template

**Assigned:** Kilo Code | **Priority:** P3

## Why

Every PR merged into this repo right now requires the author to manually decide what context to provide. A PR template takes 10 minutes to write and enforces: what changed, why, how it was tested, and whether CHANGELOG.md was updated. It reduces review time and prevents "fixed thing" PRs from being merged with no audit trail.

## Steps

1. Create `.github/pull_request_template.md`:
   ```markdown
   ## What changed
   <!-- One paragraph. What does this PR do? -->

   ## Why
   <!-- What problem does it solve? Link to task ID (e.g. T-281). -->

   ## How tested
   <!-- What commands did you run? What did you verify? -->
   - [ ] `ruff check .` passes
   - [ ] `pytest tests/ -q` passes
   - [ ] CHANGELOG.md entry written

   ## Score impact
   <!-- Which audit dimension does this improve? Repo Health / Security / Prod Readiness / Scalability / Maintainability / GitHub -->
   ```

2. Commit the file. GitHub automatically picks up `.github/pull_request_template.md` — no config needed.

3. Verify the file is valid markdown: `python -c "open('.github/pull_request_template.md').read()"` → no error.

## Done When

- [ ] `.github/pull_request_template.md` created
- [ ] Checklist includes ruff, pytest, CHANGELOG
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-336 — Add detect-secrets Baseline to CI

**Assigned:** Kilo Code | **Priority:** P3

## Why

There is no CI check for accidentally committed secrets. A developer editing `.env.example`, a scraper, or a config file could introduce a real API key. `detect-secrets` is lightweight, runs in CI, and maintains a `.secrets.baseline` file that explicitly marks false positives — so it fails only on genuinely new secrets.

## Steps

1. Add to `.github/workflows/ci.yml`, before the ruff step:
   ```yaml
   - name: detect-secrets scan
     run: |
       pip install detect-secrets
       detect-secrets scan --baseline .secrets.baseline
       detect-secrets audit .secrets.baseline --report --fail-on-unaudited
   ```

2. Generate the initial baseline on the current codebase:
   ```bash
   pip install detect-secrets
   detect-secrets scan > .secrets.baseline
   ```
   Then review the baseline: `detect-secrets audit .secrets.baseline` — mark any false positives (like `.env.example` placeholder values) as not-a-secret.

3. Commit `.secrets.baseline` — this is the approved set of "known patterns that look like secrets but aren't."

4. The CI step will fail if any new secret pattern is found that isn't in the baseline. Developers add new false positives with `detect-secrets scan --baseline .secrets.baseline` and re-commit.

## Done When

- [ ] `.secrets.baseline` generated and committed
- [ ] `detect-secrets scan` step added to CI workflow
- [ ] YAML parses cleanly
- [ ] CHANGELOG.md entry written

---

---

# T-337 — Extract Shared DB Engine Factory to utils/db.py

**Assigned:** Cline | **Priority:** P1

## Why

`create_engine(DATABASE_URL, ...)` is called in at least 8 files with inconsistent pool settings:
- `crews/board_room.py` — `pool_size=2, max_overflow=0` (wrong, needs T-318 fix)
- `utils/agent_memory.py` — `pool_size=2, max_overflow=0` (wrong, needs T-327 fix)
- `crews/market_intel_crew.py` — `pool_size=2, max_overflow=0` (wrong, needs T-327 fix)
- `agents/analyst_agent.py` — NO pool settings at all (SQLAlchemy defaults — unpredictable)
- `config/scheduler.py` — `create_engine(DATABASE_URL)` inline per job call (needs T-331 fix)
- `scrapers/kaveri_transaction_scout.py` — no pool settings
- `alembic/env.py` — `NullPool` (correct for migrations — do NOT change this one)

The fix for each file is the same: `pool_pre_ping=True, pool_size=5, max_overflow=2`. This should be a single function.

## Steps

1. Create `utils/db.py`:
   ```python
   """Shared SQLAlchemy engine factory for RE_OS."""
   import threading
   from sqlalchemy import create_engine
   from config.settings import DATABASE_URL

   _engine = None
   _lock = threading.Lock()


   def get_engine(pool_size: int = 5, max_overflow: int = 2):
       """Return the shared SQLAlchemy engine. Thread-safe singleton."""
       global _engine
       if _engine is None:
           with _lock:
               if _engine is None:
                   _engine = create_engine(
                       DATABASE_URL,
                       pool_pre_ping=True,
                       pool_size=pool_size,
                       max_overflow=max_overflow,
                   )
       return _engine
   ```

2. Replace `create_engine(...)` in the following files with `from utils.db import get_engine` + `get_engine()`:
   - `agents/analyst_agent.py` — `return create_engine(DATABASE_URL)` → `return get_engine()`
   - `scrapers/kaveri_transaction_scout.py` — inline `create_engine` → `get_engine()`

   **Do NOT replace in:**
   - `alembic/env.py` — NullPool is correct for Alembic (single-use migration connection, no pool)
   - `utils/agent_memory.py` — already has its own singleton; T-327 fixes pool size; leave for now unless combining cleanly
   - `crews/board_room.py` — same; T-318 fixes it; has own singleton; leave
   - `config/scheduler.py` — T-331 adds its own singleton with pool_size=3 (scheduler jobs need fewer connections)

3. The two immediate replacements (analyst + kaveri) are the safest — they have no existing singleton and use wrong pool config.

4. Add `utils/db.py` to the test suite — minimal test: `from utils.db import get_engine; e = get_engine(); assert e is not None`.

5. Run: `pytest tests/ -q` and `ruff check .`

## Done When

- [ ] `utils/db.py` created with `get_engine()` singleton
- [ ] `analyst_agent.py` uses `get_engine()`
- [ ] `kaveri_transaction_scout.py` uses `get_engine()`
- [ ] `alembic/env.py` unchanged (NullPool stays)
- [ ] `pytest tests/ -q` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-338 — Add pytest Markers: unit vs integration

**Assigned:** Cline | **Priority:** P1

## Why

All current tests hit the live PostgreSQL DB — `pytest tests/ -q` fails in CI when `DATABASE_URL` is not set. This means the full test suite can only run in Docker or with a local Postgres instance. Pure logic tests (validator, checkpointer, llm_router routing, crew helper functions) do not need a DB — they should run in every environment including a plain `pip install` without Docker.

Adding `unit` / `integration` markers allows:
- `pytest -m unit` — runs in seconds, no DB, works in any CI environment
- `pytest -m integration` — requires live DB, run in Docker only

## Steps

1. Open `pytest.ini` (or `pyproject.toml` `[tool.pytest.ini_options]`). Add:
   ```ini
   [pytest]
   markers =
       unit: pure Python, no DB, no network
       integration: requires live PostgreSQL DB (DATABASE_URL must be set)
   ```

2. Add `@pytest.mark.unit` to tests that need no DB:
   - `tests/test_validator.py` — all tests
   - `tests/test_checkpointer.py` — all tests
   - `tests/test_llm_router.py` — all tests
   - `tests/test_crew_helpers.py` — all tests
   - `tests/test_intel_output.py` — all tests

3. Add `@pytest.mark.integration` to tests that require a live DB:
   - `tests/test_db_organizer.py` (when T-302 is done)
   - `tests/test_board_room.py` — if any tests hit the DB (check and mark those individually)
   - `tests/test_dashboard_routes.py` (when T-328 is done) — routes that call DB paths

4. Update `.github/workflows/ci.yml`: change the pytest step to run only unit tests (no DB available in CI):
   ```yaml
   - name: pytest (unit tests only)
     run: pytest tests/ -q -m unit
   ```

5. Keep the full `pytest tests/ -q` command in `TASK_BRIEFS.md` "done when" sections — that's the Docker-local verification command.

## Done When

- [ ] `pytest.ini` (or pyproject.toml) has `unit` and `integration` markers defined
- [ ] All DB-free test files marked `@pytest.mark.unit`
- [ ] All DB-dependent test files marked `@pytest.mark.integration`
- [ ] `.github/workflows/ci.yml` runs `pytest -m unit` (no DB in CI)
- [ ] `pytest -m unit` passes with zero warnings about unknown markers
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-339 — Fix analyst_agent.py Engine: Missing Pool Settings

**Assigned:** Cline | **Priority:** P2

## Why

`agents/analyst_agent.py` has:
```python
return create_engine(DATABASE_URL)
```
No `pool_pre_ping`, no `pool_size`, no `max_overflow`. SQLAlchemy defaults give `pool_size=5` but no pre-ping — meaning stale connections from the pool silently fail on first use after a DB restart, and the agent throws an `OperationalError` mid-analysis. This task is separate from T-337 (which introduces the shared factory) because the analyst agent may need to stay at its own pool for isolation during concurrent board room sessions.

## Steps

1. Open `agents/analyst_agent.py`. Find the `create_engine(DATABASE_URL)` call (around line 22).

2. If T-337 is already done and `utils/db.py` exists:
   ```python
   from utils.db import get_engine
   # Replace the function return:
   return get_engine()
   ```

3. If T-337 is NOT done yet, apply the settings directly:
   ```python
   return create_engine(
       DATABASE_URL,
       pool_pre_ping=True,
       pool_size=5,
       max_overflow=2,
   )
   ```

4. Verify: `python -m py_compile agents/analyst_agent.py` → exit 0.

5. Run: `pytest tests/ -q`

## Done When

- [ ] `analyst_agent.py` engine has `pool_pre_ping=True, pool_size=5, max_overflow=2`
- [ ] `py_compile` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-340 — Add last_scraped_at to micro_markets + Wire into db_organizer

**Assigned:** Cline | **Priority:** P2

## Why

There is no way to know how fresh the data is for any market. A user looking at 317 Devanahalli projects has no idea if that data is from today or 3 weeks ago. `last_scraped_at TIMESTAMPTZ` on `micro_markets` is a single field that answers "when did we last successfully scrape this market?" — and feeds into a future "data freshness" warning in the dashboard and CEO brief.

## Steps

1. **Alembic migration:** Create `alembic/versions/0006_add_last_scraped_at.py`:
   ```python
   """add last_scraped_at to micro_markets"""
   revision = "0006_add_last_scraped_at"
   down_revision = "0005_drop_superseded_by"  # or current head — check alembic/versions/

   from alembic import op
   import sqlalchemy as sa

   def upgrade():
       op.add_column(
           "micro_markets",
           sa.Column("last_scraped_at", sa.TIMESTAMP(timezone=True), nullable=True),
       )

   def downgrade():
       op.drop_column("micro_markets", "last_scraped_at")
   ```
   Fill in the correct `down_revision` by checking the current head in `alembic/versions/`.

2. **schema.sql:** Add `last_scraped_at TIMESTAMPTZ` to the `micro_markets` table definition (after the last existing column, before the closing `)`).

3. **db_organizer.py:** At the end of a successful RERA or portal upsert batch for a market, update `last_scraped_at`:
   ```python
   conn.execute(
       text("""
       UPDATE micro_markets
       SET last_scraped_at = NOW()
       WHERE name ILIKE :market
       """),
       {"market": market}
   )
   ```
   Place this inside the existing transaction block — after the batch upsert, within the same commit.

4. **models.py** (if it exists and has a `MicroMarket` ORM model): add `last_scraped_at = Column(TIMESTAMP(timezone=True))`.

5. Run: `pytest tests/ -q` — confirm no test regression.

## Done When

- [ ] Alembic migration `0006_add_last_scraped_at.py` created with correct `down_revision`
- [ ] `schema.sql` updated with `last_scraped_at TIMESTAMPTZ`
- [ ] `db_organizer.py` updates `last_scraped_at` after each successful market scrape
- [ ] `models.py` updated (if it has a MicroMarket model)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-341 — v_active_projects: NULLIF Guard on absorption_pct Division

**Assigned:** Cline | **Priority:** P2

## Why

`v_active_projects` and `v_market_brief` compute absorption rates involving division. If `total_units = 0` (a project row with no unit count — possible from partial RERA data), PostgreSQL raises `division by zero` and the entire view query fails. This crashes `GET /api/db/state` and `GET /api/intel/cards` silently.

## Steps

1. Open `database/schema.sql`. Find the `absorption_pct` calculation in `v_active_projects` and `v_market_brief`.

2. Wrap the divisor in `NULLIF(..., 0)`:
   ```sql
   -- Before
   ROUND((sold_units::float / total_units) * 100, 1) AS absorption_pct

   -- After
   ROUND((sold_units::float / NULLIF(total_units, 0)) * 100, 1) AS absorption_pct
   ```
   `NULLIF(x, 0)` returns NULL when `total_units = 0` — the entire expression evaluates to NULL instead of raising an exception. The dashboard handles NULL gracefully (shows "—").

3. Apply the same fix to any Alembic migration that recreates these views:
   ```bash
   grep -rn "absorption_pct" alembic/
   ```
   Update any matches.

4. Check `agents/analyst_agent.py` for any Python-side division on `total_units` or `absorption_pct` raw values — apply the same guard (`or 1` for Python arithmetic):
   ```python
   absorption_pct = sold / max(total, 1) * 100
   ```

## Done When

- [ ] `NULLIF(total_units, 0)` applied in all `absorption_pct` divisions in `schema.sql`
- [ ] Alembic migrations updated (if any recreate the views)
- [ ] Python-side divisions in `analyst_agent.py` use `max(total, 1)` guard
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

# T-342 — Remove Stale /api/intel References

**Assigned:** Kilo Code | **Priority:** P1

## Why

T-317 deleted the `GET /api/intel` endpoint. Two stale references remain:
1. `dashboard/app.py` `_READ_ONLY_PATHS` frozenset (line ~55) still includes `'/api/intel'`
2. `dashboard/templates/index.html` (line ~1446) still calls `fetch('/api/intel')` alongside `fetch('/api/intel/cards')`. It has a `.catch(() => ({}))` so it silently fails, but it wastes a request every 30s.

## Steps

1. **`dashboard/app.py`** — remove `'/api/intel'` from the `_READ_ONLY_PATHS` frozenset. Leave all other paths.
2. **`dashboard/templates/index.html`** — find the `pollIntel` function. Remove the `fetch('/api/intel')` call and the `Promise.all([...])` wrapper if present — replace with just the `fetch('/api/intel/cards')` call.
3. `ruff check .` — pass.
4. Verify the template still polls `/api/intel/cards` and `/api/intel/download`.

## Done when

- [ ] `/api/intel` absent from `_READ_ONLY_PATHS` in app.py
- [ ] `fetch('/api/intel')` removed from index.html (not `fetch('/api/intel/cards')` — that stays)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

# T-343 — Fix datetime.utcnow() Deprecation in checkpointer.py

**Assigned:** Kilo Code | **Priority:** P2

## Why

Python 3.12 deprecated `datetime.utcnow()`. It appears in `config/checkpointer.py:~115` in the `cleanup_old()` method. The unit test suite prints 5 deprecation warnings per run — noise that masks real warnings.

## Steps

1. Open `config/checkpointer.py`.
2. Find the `cleanup_old()` method. Change:
   ```python
   from datetime import datetime, timedelta
   cutoff = (datetime.utcnow() - timedelta(days=keep_days)).date()
   ```
   to:
   ```python
   from datetime import datetime, timedelta, timezone
   cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).date()
   ```
3. Run `pytest tests/test_checkpointer.py -q` — the 5 deprecation warnings must be gone.
4. `ruff check .` — pass.

## Done when

- [ ] `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` in checkpointer.py
- [ ] `pytest tests/test_checkpointer.py -q` shows 0 warnings
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

# T-344 — GATE-2 Formal Verification: Dashboard Smoke Test

**Assigned:** Kilo Code | **Priority:** P1 | **Gate:** GATE-2

## Why

GATE-2 requires all 5 dashboard endpoints to return live (non-empty) data with the stack running. The dashboard backend is confirmed live, but the gate has never been formally checked off. Once passed, it unlocks Phase 2 DoD declaration.

## Steps

1. Start the stack: `docker compose up -d`
2. Wait 10s for containers to settle: `docker compose ps` — all must show `Up`.
3. Run each check:
   ```bash
   curl -s http://localhost:8050/api/health | python -m json.tool
   curl -s http://localhost:8050/api/agents | python -m json.tool
   curl -s http://localhost:8050/api/db/state | python -m json.tool
   curl -s http://localhost:8050/api/intel/cards | python -m json.tool
   curl -s http://localhost:8050/api/sentinel/status | python -m json.tool
   ```
4. For each endpoint: confirm the response is valid JSON and not an error/empty object.
5. If all 5 pass: mark **GATE-2 PASSED** in `TASK_QUEUE.md`. Update CLAUDE.md Phase 2 status to `✅ COMPLETE`.
6. If any endpoint fails: write a BLOCKED note with the exact error and the endpoint name.

## Done when

- [ ] All 5 endpoints return valid, non-empty JSON from live stack
- [ ] GATE-2 status updated in TASK_QUEUE.md
- [ ] CLAUDE.md Phase 2 status updated if passed
- [ ] CHANGELOG.md entry written

---

# T-345 — GATE-4 Formal Verification: Live RERA Data

**Assigned:** Kilo Code | **Priority:** P0 | **Gate:** GATE-4

## Why

GATE-4 requires ≥50 live RERA projects for Yelahanka or Hebbal (not the 8-project hardcoded fallback). T-281 added the double-space district fix and exhaustive alt-district retry. This task verifies whether it worked with a real scrape.

## Steps

1. Run the RERA scraper inside the agents container:
   ```bash
   docker compose exec agents python scrapers/rera_karnataka.py --market Yelahanka
   ```
2. Count the projects returned. The scraper logs the count. Look for `[RERA] X projects found` or check the checkpoint file.
3. If count ≥ 50:
   - Mark **GATE-4 PASSED** in TASK_QUEUE.md.
   - Update CLAUDE.md: remove the `[ESTIMATED]` warning for Yelahanka.
   - Update the open issue "RERA Portal Playwright Timeout" in CLAUDE.md — mark resolved.
4. If count < 50 or still 8 fallback:
   - Set T-345 status to BLOCKED in TASK_QUEUE.md.
   - Record the exact subdistrict tried, the error message, and whether the fallback was triggered.
   - Do NOT mark GATE-4 passed.

## Done when

- [ ] RERA scraper run completed for Yelahanka (and optionally Hebbal)
- [ ] Project count recorded in TASK_QUEUE.md notes
- [ ] GATE-4 status updated (PASSED or BLOCKED with reason)
- [ ] CLAUDE.md updated to reflect new data quality state
- [ ] CHANGELOG.md entry written

---

# T-346 — Board Room Sessions History: GET /api/board/sessions + Dashboard List

**Assigned:** Kilo Code | **Priority:** P1

## Why

Every board session is stored in DB but there's no way to browse past sessions from the dashboard. Jinu needs session history for institutional memory — reviewing what questions were asked, what the board said, what actions were extracted.

## Steps

1. **`dashboard/app.py`** — add endpoint:
   ```python
   @app.route("/api/board/sessions", methods=["GET"])
   @limiter.limit("60/minute")
   def board_sessions():
   ```
   Query `board_sessions` table: `SELECT session_id, market, status, created_at, pitch_text FROM board_sessions ORDER BY created_at DESC LIMIT 20`. Return as JSON list. Each item: `{session_id, market, status, created_at, pitch_excerpt}` where `pitch_excerpt` is first 120 chars of `pitch_text`. Use psycopg2 pool (same as other read endpoints). Handle DB failure: return `{"sessions": [], "error": "database query failed"}`.

2. Add `/api/board/sessions` to `_READ_ONLY_PATHS` frozenset in app.py.

3. **`dashboard/templates/index.html`** — in the Board Room panel, below the result div, add a "Recent Sessions" collapsible list. On page load, `fetch('/api/board/sessions')` and render: session_id (first 8 chars), market, status badge, created_at, pitch excerpt. Clicking a session loads it via `fetch('/api/board/session/<session_id>')` and calls `_renderBoardResult`. Match existing dark-terminal CSS style.

4. `ruff check .` — pass.
5. `pytest tests/ -q -m unit` — 0 failures.

## Done when

- [ ] `GET /api/board/sessions` returns last 20 sessions from live DB
- [ ] Endpoint in `_READ_ONLY_PATHS`
- [ ] Dashboard shows Recent Sessions list below Board Room panel
- [ ] Clicking a session loads its transcript into the result div
- [ ] `ruff check .` passes
- [ ] Unit tests pass (0 failures)
- [ ] CHANGELOG.md entry written

---

# T-347 — Legal Head Agent: 5th Board Room Department

**Assigned:** Kilo Code | **Priority:** P1

## Why

LLS land acquisition decisions are blocked or failed by legal risk: unclear title chains, BDA/BBMP conversion status, RERA registration gaps, encumbrance. The Board Room currently has BD, Finance, Engineering, Ops — but no legal lens. Every land pitch needs a legal read before BD or Finance can commit. This is the single highest-value gap in the board room.

## Steps

1. **Create `agents/board_room/legal_head.py`:**
   ```python
   from crewai import Agent
   from config.llm_router import get_analysis_llm

   def build_legal_head_agent():
       return Agent(
           role="Legal Head",
           goal="Identify legal, regulatory, and title risks that could block or delay this project.",
           backstory=(
               "You are the Legal Head at LLS. Your lens: RERA Karnataka registration compliance, "
               "BDA/BBMP layout approval status, encumbrance search, title chain clarity, "
               "conversion from agricultural to residential use (Section 95 of KLR Act), "
               "and proximity to regulatory overlays (airport zone, green belt, lake buffer). "
               "You respond with: CLEAR / RISK / BLOCKED. You name every unresolved legal item "
               "with its Karnataka-specific statute or regulatory body."
           ),
           llm=get_analysis_llm(),
           verbose=False,
           allow_delegation=False,
       )
   ```

2. **`crews/board_room.py`** — add `legal` to `_DEPT_TASK_TEMPLATES`:
   ```python
   "legal": (
       "Market: {market}\n"
       "Legal question: {dept_question}\n\n"
       "Respond as Legal Head. Lead with CLEAR / RISK / BLOCKED.\n"
       "Cover: RERA registration status, BDA/BBMP layout approval, title chain, "
       "encumbrance, agricultural conversion (if applicable), regulatory overlay risks "
       "(airport zone, green belt, lake buffer).\n"
       "Name every unresolved item with the applicable Karnataka statute or authority.\n"
       "Maximum 180 words."
   ),
   ```

3. **`crews/board_room.py`** — import `build_legal_head_agent` and add `"legal"` to `_run_dept_heads()` alongside the existing four. Use the same ThreadPoolExecutor pattern with 90s timeout.

4. **`dashboard/templates/index.html`** — add `legal: 'LEGAL'` to the `depts` dict in `_renderBoardResult`. Add a legal column in the board result display.

5. **`tests/test_board_room.py`** — update `test_dept_task_templates_all_four_keys` to `all_five_keys` checking `("bd", "finance", "engineering", "ops", "legal")`. Add `MOCK_DEPT_RESPONSES["legal"]` to the fixture.

6. `ruff check .` + `pytest tests/ -q -m unit` — both pass.

## Done when

- [ ] `agents/board_room/legal_head.py` created with `build_legal_head_agent()`
- [ ] `legal` template in `_DEPT_TASK_TEMPLATES`
- [ ] Legal agent runs in parallel with BD/Finance/Engineering/Ops in `_run_dept_heads()`
- [ ] Dashboard renders legal column in Board Room transcript
- [ ] Tests updated: 5-dept check passes
- [ ] `ruff check .` passes, unit tests 0 failures
- [ ] CHANGELOG.md entry written

---

# T-348 — Feasibility Micro-Tool: utils/feasibility.py

**Assigned:** Kilo Code | **Priority:** P1

## Why

LLS land acquisition decisions require quick IRR and break-even math. Currently there is no tool for this — Jinu has to do it manually. The Analyst agent should be able to run a quick feasibility check given land data from the DB and return: land cost, GDV estimate, estimated IRR, break-even PSF. This becomes the most-used tool for actual land decisions.

## Steps

1. **Create `utils/feasibility.py`:**
   ```python
   from dataclasses import dataclass

   @dataclass
   class LandFeasibility:
       land_area_sqft: float       # total site area
       land_cost_psf: float        # ₹/sqft of land
       construction_cost_psf: float # ₹/sqft of built area (default 2200)
       target_sell_psf: float      # ₹/sqft selling price
       efficiency_ratio: float = 0.65  # sellable / total built area
       fsi: float = 2.0            # floor space index for zone
       timeline_months: int = 36   # project duration

   def calc_land_cost(f: LandFeasibility) -> float:
       return f.land_area_sqft * f.land_cost_psf

   def calc_gdv(f: LandFeasibility) -> float:
       built_area = f.land_area_sqft * f.fsi
       sellable_area = built_area * f.efficiency_ratio
       return sellable_area * f.target_sell_psf

   def calc_construction_cost(f: LandFeasibility) -> float:
       return f.land_area_sqft * f.fsi * f.construction_cost_psf

   def calc_breakeven_psf(f: LandFeasibility) -> float:
       total_cost = calc_land_cost(f) + calc_construction_cost(f)
       sellable_area = f.land_area_sqft * f.fsi * f.efficiency_ratio
       return total_cost / max(sellable_area, 1)

   def calc_profit_margin(f: LandFeasibility) -> float:
       gdv = calc_gdv(f)
       total_cost = calc_land_cost(f) + calc_construction_cost(f)
       return (gdv - total_cost) / max(gdv, 1) * 100

   def calc_simple_irr(f: LandFeasibility) -> float:
       """Simple annualised return proxy. Not DCF — use for quick go/no-go only."""
       gdv = calc_gdv(f)
       total_cost = calc_land_cost(f) + calc_construction_cost(f)
       profit = gdv - total_cost
       years = f.timeline_months / 12
       return (profit / max(total_cost, 1)) / max(years, 0.5) * 100

   def feasibility_summary(f: LandFeasibility) -> dict:
       return {
           "land_cost_total": round(calc_land_cost(f)),
           "construction_cost_total": round(calc_construction_cost(f)),
           "gdv": round(calc_gdv(f)),
           "breakeven_psf": round(calc_breakeven_psf(f)),
           "profit_margin_pct": round(calc_profit_margin(f), 1),
           "simple_irr_pct": round(calc_simple_irr(f), 1),
           "verdict": "GO" if calc_profit_margin(f) >= 20 else ("MARGINAL" if calc_profit_margin(f) >= 12 else "NO-GO"),
       }
   ```

2. **Wire to analyst**: In `agents/analyst_agent.py`, add a `FeasibilityTool` that calls `feasibility_summary()`. The tool accepts `land_area_sqft`, `land_cost_psf`, `target_sell_psf` from the market brief data (use avg_listing_psf from v_market_brief as target_sell_psf). The analyst can invoke it when asked to assess a site.

3. **Unit tests** — create `tests/test_feasibility.py` marked `@pytest.mark.unit`. Test: `calc_breakeven_psf`, `calc_profit_margin`, `calc_simple_irr`, `feasibility_summary` verdict thresholds (≥20% = GO, 12-19% = MARGINAL, <12% = NO-GO). At least 8 tests.

4. `ruff check .` + `pytest tests/ -q -m unit` — both pass.

## Done when

- [ ] `utils/feasibility.py` created with all 7 functions
- [ ] `FeasibilityTool` added to `agents/analyst_agent.py`
- [ ] `tests/test_feasibility.py` with ≥8 unit tests, all pass
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

# T-349 — Dashboard DB Explorer Panel

**Assigned:** Kilo Code | **Priority:** P2

## Why

Jinu needs to see what data exists in the DB without running psql commands. Three key views tell the story: market inventory, developer scorecard, active projects. A simple sortable table panel in the dashboard gives direct visibility.

## Steps

1. **`dashboard/app.py`** — add endpoint:
   ```python
   @app.route("/api/db/tables", methods=["GET"])
   @limiter.limit("30/minute")
   def db_tables():
   ```
   Add `/api/db/tables` to `_READ_ONLY_PATHS`.
   Query three views with the psycopg2 pool:
   - `SELECT * FROM v_market_inventory` (market summary)
   - `SELECT developer_name, grade, project_count, market_names FROM v_developer_scorecard LIMIT 50`
   - `SELECT project_name, developer_name, market, status, total_units, avg_listing_psf FROM v_active_projects LIMIT 100`
   Return: `{"market_inventory": [...], "developer_scorecard": [...], "active_projects": [...]}`. Handle DB failure generically.

2. **`dashboard/templates/index.html`** — add a "DB Explorer" tab/section (after the Board Room panel). On click, `fetch('/api/db/tables')` and render three HTML tables with sortable headers. Use `<table>` with dark-terminal styling matching existing panels. Columns for each view match the SELECT above. Add a "Refresh" button.

3. `ruff check .` — pass. Check dashboard renders without JS errors.

## Done when

- [ ] `GET /api/db/tables` returns all three view datasets
- [ ] Dashboard shows DB Explorer panel with three sortable tables
- [ ] Tables render with correct column headers
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

# T-350 — config/scheduler.py: Use Shared get_engine()

**Assigned:** Kilo Code | **Priority:** P2

## Why

`config/scheduler.py` has its own `_get_scheduler_engine()` singleton (same pattern that was cleaned up in crews/board_room.py and crews/market_intel_crew.py this sprint). Scheduler runs in a separate container, so it won't share the pool with the agents container — but consolidating to `utils/db.py` removes the duplicate code and ensures consistent pool settings.

## Steps

1. **`config/scheduler.py`** — remove `_scheduler_engine` global + `_get_scheduler_engine()` function.
2. Add `from utils.db import get_engine` at the top.
3. Replace all `_get_scheduler_engine()` call sites with `get_engine()`.
4. Also remove `from sqlalchemy import create_engine` and `from config.settings import DATABASE_URL` if they're now unused (check before removing — `DATABASE_URL` may be used elsewhere in the file for other purposes).
5. `ruff check .` — pass. `pytest tests/ -q -m unit` — 0 failures.

## Done when

- [ ] `_get_scheduler_engine()` and `_scheduler_engine` removed from scheduler.py
- [ ] All call sites use `get_engine()` from utils.db
- [ ] `ruff check .` passes, unit tests 0 failures
- [ ] CHANGELOG.md entry written

---

# T-351 — Scheduler: Add Nightly Devanahalli + Hebbal RERA Cron Jobs

**Assigned:** Kilo Code | **Priority:** P2

## Why

The scheduler currently runs RERA for all three markets in a single 2AM UTC job. If that job fails mid-way, we don't know which markets succeeded. Splitting into per-market jobs gives: independent failure isolation, per-market scheduling flexibility, and cleaner logs.

## Steps

1. Open `config/scheduler.py`. Find the existing RERA scrape cron job.
2. If it's a single "all markets" job: split into three independent jobs:
   - Yelahanka: `cron(hour=21, minute=0)` (2:30AM IST = 9:00PM UTC previous day)
   - Devanahalli: `cron(hour=21, minute=30)` (3:00AM IST = 9:30PM UTC)
   - Hebbal: `cron(hour=22, minute=0)` (3:30AM IST = 10:00PM UTC)
3. Each job runs: `subprocess.Popen(["python", "scrapers/rera_karnataka.py", "--market", "<Market>"])` (same pattern used for dashboard-triggered runs).
4. Each job logs start + completion to `agent_runs` via `_write_stage_event` or the existing logging pattern.
5. `ruff check .` — pass. `pytest tests/ -q -m unit` — 0 failures.

Note: If the scheduler already has per-market jobs (check before changing), just verify they're wired to all three markets and adjust the timing to the above schedule.

## Done when

- [ ] Three separate RERA cron jobs: Yelahanka, Devanahalli, Hebbal
- [ ] IST timing: 2:30, 3:00, 3:30AM IST respectively
- [ ] Each job runs independently (no shared state)
- [ ] `ruff check .` passes, unit tests 0 failures
- [ ] CHANGELOG.md entry written

---

*End of Task Briefs — Stage 3*
