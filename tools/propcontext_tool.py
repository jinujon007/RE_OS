"""PropContext MCP Integration — CrewAI Tools.

Cross-references RE_OS RERA data against PropContext MCP.
Three tools: search_projects, get_developer_projects, check_rera_compliance.
MCP absent -> return empty results gracefully.

Architecture:
  - _MCPClient: persistent SSE/HTTP client for MCP JSON-RPC protocol.
    Uses a daemon thread to keep the SSE connection alive while
    dispatching tool calls. Falls back to direct HTTP POST if SSE fails.
  - Tools: three CrewAI BaseTool subclasses, each wrapping one MCP action.
  - Singleton client at module level; _close_client() for lifecycle.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, ClassVar

from crewai.tools import BaseTool
from loguru import logger

__all__ = [
    "PropContextSearchTool",
    "PropContextDeveloperTool",
    "PropContextComplianceTool",
    "_close_client",
]

PROPCONTEXT_MCP_URL: str = os.environ.get(
    "PROPCONTEXT_MCP_URL",
    "https://propcontext-production.up.railway.app/mcp",
)

_EMPTY: dict[str, Any] = {"status": "unavailable", "content": []}


class _MCPClient:
    """Minimal async-free MCP SSE client for PropContext.

    Two-phase connection:
      1. **Direct POST** — sends JSON-RPC via HTTP POST to the MCP URL.
         If the server returns 200, we use this stateless path.
      2. **SSE session** — if direct POST fails, opens GET /mcp with SSE,
         reads the session endpoint, then POSTs JSON-RPC there. A daemon
         thread keeps the SSE stream alive while the client is active.

    Thread-safe for single-threaded CrewAI usage. Never raises —
    all errors degrade to ``{"status": "unavailable", "content": []}``.
    """

    _json_rpc_id: ClassVar[int] = 0
    _json_rpc_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, url: str = PROPCONTEXT_MCP_URL) -> None:
        self._url: str = url
        self._message_url: str | None = None
        self._client: Any = None  # httpx.Client
        self._sse_thread: threading.Thread | None = None
        self._sse_stop: threading.Event = threading.Event()

    # ── Helpers ──────────────────────────────────────────────────────────

    @classmethod
    def _next_id(cls) -> int:
        with cls._json_rpc_lock:
            cls._json_rpc_id += 1
            return cls._json_rpc_id

    def _ensure_client(self) -> None:
        if self._client is None:
            import httpx
            self._client = httpx.Client(timeout=10.0)

    def _close_sse(self) -> None:
        self._sse_stop.set()
        if self._sse_thread and self._sse_thread.is_alive():
            self._sse_thread.join(timeout=3)
        self._sse_thread = None

    # ── Connection ───────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Establish connection — tries direct POST first, then SSE."""
        if self._message_url:
            return True
        # 1. Try direct POST (some MCP servers support stateless JSON-RPC)
        if self._try_direct_post():
            return True
        # 2. Try SSE session
        return self._connect_sse()

    def _try_direct_post(self) -> bool:
        """POST JSON-RPC list-tools directly; if it works, use stateless path."""
        self._ensure_client()
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/list",
                "params": {},
            }
            resp = self._client.post(self._url, json=payload, timeout=10.0)
            if resp.status_code == 200:
                body = resp.json()
                if "result" in body or "error" in body:
                    self._message_url = self._url
                    return True
        except Exception as exc:
            logger.debug("[PropContext] direct POST failed: %s", exc)
        return False

    def _connect_sse(self) -> bool:
        """Connect via SSE, extract session endpoint, keep connection alive.

        The SSE loop runs entirely in a daemon thread so the stream stays open
        after the endpoint is found. Main thread waits up to 10s for the
        endpoint event, then returns based on whether _message_url was set.
        """
        self._ensure_client()
        self._sse_stop.clear()
        _endpoint_found = threading.Event()

        def _sse_loop() -> None:
            try:
                with self._client.stream(
                    "GET", self._url,
                    headers={"Accept": "text/event-stream"},
                ) as resp:
                    event: str | None = None
                    data_lines: list[str] = []
                    for line in resp.iter_lines():
                        if self._sse_stop.is_set():
                            break
                        if not line:
                            if data_lines and event == "endpoint":
                                raw = "".join(data_lines)
                                try:
                                    payload = json.loads(raw)
                                    ep = payload.get("endpoint", "")
                                    if ep.startswith("/"):
                                        from urllib.parse import urlparse
                                        parsed = urlparse(self._url)
                                        ep = f"{parsed.scheme}://{parsed.netloc}{ep}"
                                    self._message_url = ep
                                except (json.JSONDecodeError, KeyError):
                                    pass
                                _endpoint_found.set()
                            event = None
                            data_lines = []
                        elif line.startswith("event: "):
                            event = line[7:].strip()
                        elif line.startswith("data: "):
                            data_lines.append(line[6:])
            except Exception as exc:
                logger.debug("[PropContext] SSE loop failed: %s", exc)
            finally:
                _endpoint_found.set()  # unblock waiter on failure too

        self._sse_thread = threading.Thread(
            target=_sse_loop, daemon=True, name="propcontext-sse"
        )
        self._sse_thread.start()
        _endpoint_found.wait(timeout=10.0)
        return bool(self._message_url)

    # ── Tool invocation ──────────────────────────────────────────────────

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._message_url and not self.connect():
            return dict(_EMPTY)

        self._ensure_client()
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        try:
            resp = self._client.post(self._message_url, json=payload, timeout=15.0)
            if resp.status_code == 200:
                body = resp.json()
                if "result" in body:
                    return body["result"]
                error = body.get("error", {})
                logger.debug("[PropContext] tool %s error: %s", name, error.get("message"))
                return {"status": "error", "content": [], "error": error.get("message", "unknown")}
            logger.debug("[PropContext] tool %s HTTP %s", name, resp.status_code)
        except Exception as exc:
            logger.debug("[PropContext] tool call %s failed: %s", name, exc)

        return dict(_EMPTY)

    def close(self) -> None:
        self._close_sse()
        if self._client:
            self._client.close()
            self._client = None
        self._message_url = None


# ── Module-level client singleton ─────────────────────────────────────────

_client: _MCPClient | None = None
_client_lock = threading.Lock()


def _get_client() -> _MCPClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _MCPClient()
    return _client


# ── Helpers ────────────────────────────────────────────────────────────────


def _empty_results(action: str, reason: str = "MCP unavailable") -> str:
    return json.dumps({
        "status": "unavailable",
        "source": "propcontext",
        "action": action,
        "reason": reason,
        "results": [],
    })


def _try_call(action: str, mcp_tool: str, params: dict[str, Any] | None = None) -> str:
    try:
        client = _get_client()
        result = client.call_tool(mcp_tool, params or {})
        if result.get("status") == "unavailable":
            return _empty_results(action, "MCP endpoint unreachable")
        content = result.get("content", [])
        if isinstance(content, list):
            return json.dumps({
                "status": "ok",
                "source": "propcontext",
                "action": action,
                "results": content,
                "count": len(content),
            })
        return json.dumps({
            "status": "ok",
            "source": "propcontext",
            "action": action,
            "results": content,
        })
    except Exception as exc:
        logger.debug("[PropContext] %s failed: %s", action, exc)
        return _empty_results(action, str(exc))


# ── Tool 1: Search Projects ──────────────────────────────────────────────


class PropContextSearchTool(BaseTool):
    """Search RERA projects via PropContext MCP.

    Input: JSON with 'query' (str — project name or location) and
    optional 'market' (str — e.g. 'Yelahanka').
    Returns: list of matching projects with RERA registration details.
    When PropContext is unreachable, returns status='unavailable'.
    """

    name: str = "propcontext_search_projects"
    description: str = (
        "Search for RERA projects via PropContext MCP by project name or location. "
        "Input: JSON with 'query' (str) and optional 'market' (str). "
        "Returns: list of matching projects with RERA details. "
        "Returns empty when PropContext MCP is unreachable."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return _empty_results("search_projects", "invalid JSON input")
        query = str(params.get("query", "")).strip()
        market = str(params.get("market", "")).strip()
        if not query:
            return _empty_results("search_projects", "empty query")
        call_params: dict[str, str] = {"query": query}
        if market:
            call_params["market"] = market
        return _try_call("search_projects", "search_projects", call_params)


# ── Tool 2: Get Developer Projects ───────────────────────────────────────


class PropContextDeveloperTool(BaseTool):
    """Get projects for a specific developer via PropContext MCP.

    Input: JSON with 'developer_name' (str).
    Returns: list of RERA projects by that developer.
    When PropContext is unreachable, returns status='unavailable'.
    """

    name: str = "propcontext_developer_projects"
    description: str = (
        "Get projects for a specific developer via PropContext MCP. "
        "Input: JSON with 'developer_name' (str). "
        "Returns: list of RERA projects by that developer. "
        "Returns empty when PropContext MCP is unreachable."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return _empty_results("developer_projects", "invalid JSON input")
        developer = str(params.get("developer_name", "")).strip()
        if not developer:
            return _empty_results("developer_projects", "empty developer_name")
        return _try_call(
            "developer_projects",
            "get_developer_projects",
            {"developer_name": developer},
        )


# ── Tool 3: Check RERA Compliance ────────────────────────────────────────


class PropContextComplianceTool(BaseTool):
    """Check RERA compliance status for a project via PropContext MCP.

    Input: JSON with 'project_name' (str).
    Returns: compliance details (registration status, completion status,
    compliance flags). When PropContext is unreachable, returns
    status='unavailable'.
    """

    name: str = "propcontext_rera_compliance"
    description: str = (
        "Check RERA compliance status for a project via PropContext MCP. "
        "Input: JSON with 'project_name' (str). "
        "Returns: compliance details including registration status, "
        "completion status, and any compliance flags. "
        "Returns empty when PropContext MCP is unreachable."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return _empty_results("rera_compliance", "invalid JSON input")
        project = str(params.get("project_name", "")).strip()
        if not project:
            return _empty_results("rera_compliance", "empty project_name")
        return _try_call(
            "rera_compliance",
            "check_rera_compliance",
            {"project_name": project},
        )


# ── Lifecycle ──────────────────────────────────────────────────────────────


def _close_client() -> None:
    """Close the module-level MCP client singleton.

    Safe to call multiple times. Idempotent. Call during app shutdown
    to release SSE connections and HTTP connection pools.
    """
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.debug("[PropContext] client closed")
