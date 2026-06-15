"""
RE_OS — Ingest Base (Sprint 61 — Unified Ingest Engine)

Defines the core abstractions for the plugin-based ingest pipeline:

    DataPlugin      — abstract base class every ingest plugin implements
    ParsedRecord    — canonical output record produced by a plugin run
    ValidationResult — lightweight validation outcome for a single record

Every plugin produces a list of ParsedRecords. The engine collects,
deduplicates, validates, and writes them via IngestWriter.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "DataPlugin",
    "ParsedRecord",
    "ValidationResult",
]


@dataclass
class ParsedRecord:
    """Normalised output from a single scrape/extraction.

    Fields:
        entity_type: Stable logical type key (e.g. ``"rera_project"``).
        source_id:   Unique identifier *within this plugin* for the record.
        market:      Canonical market name (e.g. ``"Yelahanka"``).
        data:        Column-value dict that will be UPSERTed into the target table.
        raw_hash:    SHA-256 of *data* — computed automatically on first access.
        confidence:  [0,1] estimate of data quality (default 1.0).
        scraped_at:  Timestamp of the original scrape (defaults to now UTC).
    """

    entity_type: str
    source_id: str
    market: str
    data: dict[str, Any]
    raw_hash: str = ""
    confidence: float = 1.0
    scraped_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.scraped_at is None:
            object.__setattr__(self, "scraped_at", datetime.now(timezone.utc))
        if not self.raw_hash:
            raw = json.dumps(self.data, sort_keys=True, default=str).encode("utf-8")
            object.__setattr__(self, "raw_hash", hashlib.sha256(raw).hexdigest())

    @classmethod
    def compute_hash(cls, data: dict[str, Any]) -> str:
        """Deterministic SHA-256 hex digest of a data dict (stable across runs).

        Example::

            h = ParsedRecord.compute_hash({"project_name": "Nova"})
            # "a1b2c3d4e5f6..."
        """
        raw = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def __repr__(self) -> str:
        return (
            f"ParsedRecord(entity_type={self.entity_type!r}, "
            f"source_id={self.source_id!r}, market={self.market!r}, "
            f"confidence={self.confidence}, hash={self.raw_hash[:12]}…)"
        )


@dataclass
class ValidationResult:
    """Immutable validation outcome for a single :class:`ParsedRecord`.

    ``valid`` is ``True`` only when the errors list is empty.
    """

    valid: bool
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid

    def __repr__(self) -> str:
        if self.valid:
            return "ValidationResult(VALID)"
        return f"ValidationResult(INVALID, errors={self.errors})"


class DataPlugin(ABC):
    """Abstract base for all ingest data-source plugins.

    Subclasses must define :attr:`plugin_id`, :attr:`source_id`,
    and implement :meth:`run`.

    The default :meth:`validate` checks structural fields only;
    override for schema-level validation per entity type.
    """

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Stable unique identifier used in logs and the ingest_log table."""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Source identifier logged in ingest_log.source_id (portal name, API name, …)."""

    @abstractmethod
    def run(self, market: str) -> list[ParsedRecord]:
        """Execute the plugin for *market* and return discovered records.

        Raises:
            Exception: Any scraper-level failure (the engine handles retries).
        """

    def validate(self, record: ParsedRecord) -> ValidationResult:
        """Return a :class:`ValidationResult` for *record*.

        Override this to add entity-type-specific schema checks.
        The base implementation validates structural requirements:
        non-empty entity_type, source_id, and data.
        """
        errors: list[str] = []
        if not record.entity_type:
            errors.append("entity_type is required")
        if not record.source_id:
            errors.append("source_id is required")
        if not record.data:
            errors.append("data dict is required")
        return ValidationResult(valid=not errors, errors=errors)
