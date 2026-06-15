"""
RE_OS — Spatial Intelligence (Tier 3 — Geospatial Depth)
PySAL Moran's I spatial autocorrelation on PSF values.
Detects clustering patterns in project price distributions.
"""

from dataclasses import dataclass
from typing import Optional
from loguru import logger

__all__ = ["SpatialAutocorrelationResult", "SpatialClusterAnalyzer"]


@dataclass
class SpatialAutocorrelationResult:
    morans_i: float = 0.0
    p_value: float = 1.0
    z_score: float = 0.0
    pattern: str = "unknown"  # clustered, dispersed, random
    n_projects: int = 0
    market: str = ""
    interpretation: str = ""


class SpatialClusterAnalyzer:
    """Compute Moran's I spatial autocorrelation on project PSF values.

    Detects whether high/low PSF values cluster spatially (clustered),
    repel (dispersed), or appear random.

    Gracefully degrades when PySAL unavailable or too few projects.
    """

    _MIN_PROJECTS = 10

    def analyze_market(self, market: str) -> SpatialAutocorrelationResult:
        """Compute spatial autocorrelation for all projects in a market.

        Args:
            market: Market name (Yelahanka/Devanahalli/Hebbal).

        Returns:
            SpatialAutocorrelationResult with Moran's I, p-value, pattern.
        """
        result = SpatialAutocorrelationResult(market=market)

        try:
            from utils.db import get_engine
            from sqlalchemy import text

            with get_engine().connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT rp.price_min_psf, rp.price_max_psf,
                               ST_X(rp.geom) AS lon, ST_Y(rp.geom) AS lat
                        FROM rera_projects rp
                        JOIN micro_markets m ON m.id = rp.micro_market_id
                        WHERE m.name ILIKE :m
                          AND rp.geom IS NOT NULL
                          AND rp.price_min_psf IS NOT NULL
                        LIMIT 500
                    """),
                    {"m": f"%{market}%"},
                ).fetchall()

            if len(rows) < self._MIN_PROJECTS:
                result.interpretation = f"Only {len(rows)} projects with geometry (need ≥{self._MIN_PROJECTS})"
                logger.info("[SpatialIntel] %s: %s", market, result.interpretation)
                return result

            import numpy as np

            coords = []
            values = []
            seen_locs = set()
            for r in rows:
                psf_min, psf_max, lon, lat = r
                if not (lon and lat):
                    continue
                avg_psf = (
                    (float(psf_min or 0) + float(psf_max or 0)) / 2
                    if psf_min or psf_max
                    else 0
                )
                loc_key = (round(float(lon), 4), round(float(lat), 4))
                if loc_key in seen_locs:
                    continue
                seen_locs.add(loc_key)
                coords.append((float(lon), float(lat)))
                values.append(avg_psf)

            result.n_projects = len(values)

            if len(values) < self._MIN_PROJECTS:
                result.interpretation = f"Only {len(values)} valid project locations"
                return result

            try:
                import libpysal
                from esda.moran import Moran

                w = libpysal.weights.KNN.from_array(coords, k=5)
                w.transform = "r"

                moran = Moran(np.array(values), w)
                result.morans_i = float(moran.I)
                result.p_value = float(moran.p_sim)
                result.z_score = float(moran.z_sim)

                if result.p_value < 0.05:
                    if result.morans_i > 0:
                        result.pattern = "clustered"
                        result.interpretation = (
                            f"Strong spatial clustering (I={result.morans_i:.3f}, p={result.p_value:.4f}). "
                            f"Similar PSF values group together — location premium is significant."
                        )
                    else:
                        result.pattern = "dispersed"
                        result.interpretation = (
                            f"Spatial dispersion (I={result.morans_i:.3f}, p={result.p_value:.4f}). "
                            f"PSF values vary randomly across locations."
                        )
                else:
                    result.pattern = "random"
                    result.interpretation = (
                        f"No significant spatial pattern (I={result.morans_i:.3f}, p={result.p_value:.4f}). "
                        f"PSF distribution appears random across the market."
                    )

                logger.info(
                    "[SpatialIntel] %s: %s (I=%.3f, p=%.4f, n=%d)",
                    market,
                    result.pattern,
                    result.morans_i,
                    result.p_value,
                    result.n_projects,
                )

            except ImportError:
                result.interpretation = "PySAL not available (pip install pysal)"
                logger.debug("[SpatialIntel] %s", result.interpretation)

        except Exception as exc:
            logger.warning("[SpatialIntel] Failed for %s: %s", market, exc)
            result.interpretation = f"Analysis failed: {exc}"

        return result

    def format_for_ceo(self, result: SpatialAutocorrelationResult) -> str:
        """Format analysis result for CEO agent synthesis."""
        if result.n_projects < self._MIN_PROJECTS:
            return f"[Spatial] {result.market}: insufficient data ({result.n_projects} projects)"

        emoji = {"clustered": "🔴", "dispersed": "🟢", "random": "🟡"}.get(
            result.pattern, "⚪"
        )
        return (
            f"{emoji} [Spatial] {result.market}: {result.pattern.upper()} "
            f"(I={result.morans_i:.3f}, p={result.p_value:.4f}, n={result.n_projects})\n"
            f"{result.interpretation[:200]}"
        )
