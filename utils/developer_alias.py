"""Developer alias resolver — normalises developer name variants to canonical.

Thread-safe. Uses word-boundary matching to avoid substring false positives.
"""

import re
import threading

__all__ = ["DeveloperAliasResolver"]


class DeveloperAliasResolver:
    _aliases: dict[str, list[re.Pattern]] | None = None
    _lock = threading.Lock()

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._aliases = None

    @classmethod
    def _load(cls):
        if cls._aliases is not None:
            return
        with cls._lock:
            if cls._aliases is not None:
                return
            try:
                from config.settings import DEVELOPER_ALIASES
            except Exception as exc:
                raise RuntimeError(
                    f"DeveloperAliasResolver: cannot load DEVELOPER_ALIASES from settings: {exc}"
                ) from exc
            cls._aliases = {}
            for canonical, variants in DEVELOPER_ALIASES.items():
                compiled = []
                for v in variants:
                    v_escaped = re.escape(v.strip().lower())
                    compiled.append(re.compile(rf"\b{v_escaped}\b", re.I))
                cls._aliases[canonical] = compiled

    @classmethod
    def canonical(cls, raw_name: str) -> str:
        cls._load()
        raw = (raw_name or "").strip()
        if not raw:
            return raw
        assert cls._aliases is not None
        for canonical, patterns in cls._aliases.items():
            for pattern in patterns:
                if pattern.search(raw):
                    return canonical
        return raw
