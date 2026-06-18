"""
ETag support for read-heavy endpoints.
"""

import hashlib
import json

from fastapi import Request
from fastapi.responses import Response


def compute_etag(data: dict | list | None) -> str:
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:16]


def check_etag(request: Request, etag: str) -> Response | None:
    if_none_match = request.headers.get("If-None-Match", "")
    raw = if_none_match.strip('" ')
    if raw == "*" or raw == etag:
        return Response(
            status_code=304,
            headers={
                "ETag": f'"{etag}"',
                "Cache-Control": "private, max-age=30, must-revalidate",
            },
        )
    return None


def add_etag(response: Response, data: dict | list | None, cache_ttl: int = 30) -> str:
    etag = compute_etag(data)
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = f"private, max-age={cache_ttl}, must-revalidate"
    return etag


def etag_response(request: Request, data: dict | list | None, cache_ttl: int = 30) -> Response | None:
    """Convenience: check ETag, return 304 on match or None so caller returns JSONResponse with headers."""
    etag = compute_etag(data)
    cached = check_etag(request, etag)
    if cached:
        return cached
    return None
