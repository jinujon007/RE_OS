import argparse
import random
import uuid
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import text

from utils.db import get_engine

MARKETS = {
    "Yelahanka": {
        "id": "0a10553b-cc39-4ca0-ae83-5fc1643b912c",
        "psf_range": (6000, 12000),
    },
    "Devanahalli": {
        "id": "f796fadf-6fcc-46ae-b5f8-6af2a9784468",
        "psf_range": (4000, 8000),
    },
    "Hebbal": {
        "id": "c7b25515-c290-49b5-bb04-82378dc6b1b8",
        "psf_range": (8000, 15000),
    },
}

PROJECT_TEMPLATES = {
    "Yelahanka": [
        ("Prestige", ["Prestige Lakeside Habitat", "Prestige Ficus", "Prestige Falcon City"]),
        ("Sobha", ["Sobha City", "Sobha Silicon Oasis", "Sobha Forest View"]),
        ("Brigade", ["Brigade Utopia", "Brigade Lakefront", "Brigade Palm Springs"]),
        ("Total Environment", ["Total Environment Purva Sky", "Total Environment Windmills"]),
        ("Godrej", ["Godrej Splendour", "Godrej Woodland"]),
        ("Assetz", ["Assetz Marq", "Assetz 63 Degree East"]),
        ("Shriram", ["Shriram North County", "Shriram Palm Grove"]),
        ("NVT", ["NVT Adonia", "NVT Elements"]),
        ("Century", ["Century Aurora", "Century Green Hills"]),
        ("Purvankara", ["Puravankara Purva Park", "Purva Venezia"]),
        ("Mahindra", ["Mahindra Luminare", "Mahindra Eden"]),
        ("DLF", ["DLF City", "DLF New Town"]),
        ("Adani", ["Adani Samsara", "Adani Avante"]),
        ("Lodha", ["Lodha Palava", "Lodha Bellona", "Lodha Meridian"]),
    ],
    "Devanahalli": [
        ("Brigade", ["Brigade Gateway", "Brigade North Crest", "Brigade Sanctuary"]),
        ("Prestige", ["Prestige Skyline", "Prestige Park Plaza", "Prestige Airport Village", "Prestige Air Residency"]),
        ("Godrej", ["Godrej Ananda", "Godrej Frontier"]),
        ("Total Environment", ["Total Environment Canyon", "Total Environment Peaks"]),
        ("Assetz", ["Assetz Northstar", "Assetz Flight Deck"]),
        ("NVT", ["NVT Aeros", "NVT Horizon"]),
        ("Century", ["Century Aero", "Century Nova"]),
        ("Sattva", ["Sattva Aeron", "Sattva Skypark"]),
        ("Shriram", ["Shriram Aero City", "Shriram North Star"]),
        ("Mahindra", ["Mahindra Eden", "Mahindra Aerocity"]),
        ("DLF", ["DLF Aeropolis", "DLF Air Village"]),
        ("Lodha", ["Lodha Aero", "Lodha Skyward"]),
        ("Adani", ["Adani North Reach", "Adani Aviator"]),
        ("Sobha", ["Sobha Aero", "Sobha Skylife"]),
    ],
    "Hebbal": [
        ("Prestige", ["Prestige Glenwood", "Prestige Kew Gardens", "Prestige Ozone"]),
        ("Brigade", ["Brigade Meridian", "Brigade Vantage", "Brigade Cornerstone"]),
        ("Sobha", ["Sobha International City", "Sobha City Vista"]),
        ("Godrej", ["Godrej Ascend", "Godrej Brookfield"]),
        ("Assetz", ["Assetz Solitaire", "Assetz Downtown"]),
        ("Puravankara", ["Puravankara Aspira", "Purva Westbrook"]),
        ("Shriram", ["Shriram Southern Rise", "Shriram Lake Crest"]),
        ("NVT", ["NVT Metropolis", "NVT Skylight"]),
        ("Century", ["Century Central", "Century Summit"]),
        ("Mahindra", ["Mahindra Vista", "Mahindra Pinnacle"]),
        ("DLF", ["DLF Midtown", "DLF Oakwood"]),
        ("Adani", ["Adani Central", "Adani Summit"]),
        ("Lodha", ["Lodha Elite", "Lodha Crown"]),
        ("Tata", ["Tata Promont", "Tata North Park"]),
    ],
}

BHK_CONFIGS = ["1 BHK", "2 BHK", "3 BHK", "4 BHK"]
AREA_RANGES = [(600, 900), (900, 1300), (1300, 1800), (1800, 2500)]


def ensure_minimum_listings(count: int, market_name: str, market_config: dict, templates: list, seed: int) -> list[dict]:
    """Generate at least `count` listings for a market, cycling templates as needed."""
    generated = []
    cycles = 0
    max_cycles = 5
    while len(generated) < count and cycles < max_cycles:
        generated.extend(_generate_batch(market_name, market_config, templates, seed + cycles))
        cycles += 1
    if len(generated) < count:
        logger.warning(f"[SeedListings] {market_name}: only {len(generated)} after {max_cycles} cycles (need {count})")
    return generated[:count]


def _generate_batch(market_name: str, market_config: dict, templates: list, cycle_seed: int) -> list[dict]:
    """Generate one listing per developer-project template entry.

    Deterministic within a cycle_seed so re-running with the same seed produces
    identical output for the templates defined.
    """
    local_rng = random.Random(cycle_seed)
    market_id = market_config["id"]
    psf_min, psf_max = market_config["psf_range"]
    batch = []
    for developer, projects in templates:
        for project in projects:
            bhk = local_rng.choice(BHK_CONFIGS)
            area_min, area_max = local_rng.choice(AREA_RANGES)
            area = local_rng.randint(area_min, area_max)
            psf = local_rng.randint(psf_min, psf_max)
            price = area * psf
            days_ago = local_rng.randint(0, 60)
            scraped_at = datetime.now() - timedelta(days=days_ago)
            local_id = f"{market_name}_{project}"
            batch.append({
                "id": str(uuid.uuid4()),
                "source": "seed_estimated",
                "source_listing_id": local_id,
                "source_url": None,
                "micro_market_id": market_id,
                "rera_project_id": None,
                "property_type": local_rng.choice(["Apartment", "Apartment", "Apartment", "Villa"]),
                "transaction_type": "Sale",
                "bhk_config": bhk,
                "carpet_area_sqft": area,
                "built_up_area_sqft": round(area * local_rng.uniform(1.1, 1.25)),
                "super_built_up_sqft": round(area * local_rng.uniform(1.25, 1.4)),
                "plot_area_sqft": None,
                "listed_price": price,
                "price_psf": psf,
                "monthly_rent": None,
                "security_deposit": None,
                "deposit_months": None,
                "address": None,
                "locality": market_name,
                "listed_at": scraped_at.date(),
                "is_active": True,
                "days_on_market": days_ago,
                "is_new_launch": local_rng.random() < 0.2,
                "is_rera_registered": local_rng.random() < 0.7,
                "raw_rera_number": None,
                "raw_data": None,
                "data_source": "seed_estimated",
            })
    return batch


def generate_listings(market_name: str, market_config: dict, seed: int = 42, minimum: int = 30) -> list[dict]:
    """Generate seed listings for one market with reproducible randomness.

    Args:
        market_name: One of MARKETS.keys().
        market_config: Dict with 'id' and 'psf_range'.
        seed: Deterministic seed for reproducibility (default 42).
        minimum: Minimum number of listings to generate (default 30).

    Returns:
        List of listing dicts ready for DB insertion.
    """
    templates = PROJECT_TEMPLATES[market_name]
    listings = ensure_minimum_listings(minimum, market_name, market_config, templates, seed)
    logger.info(f"[SeedListings] Generated {len(listings)} listings for {market_name}")
    return listings


_INSERT_COLUMNS = [
    "id", "source", "source_listing_id", "source_url",
    "micro_market_id", "rera_project_id", "property_type",
    "transaction_type", "bhk_config", "carpet_area_sqft",
    "built_up_area_sqft", "super_built_up_sqft", "plot_area_sqft",
    "listed_price", "price_psf", "monthly_rent", "security_deposit",
    "deposit_months", "address", "locality", "listed_at",
    "is_active", "days_on_market", "is_new_launch",
    "is_rera_registered", "raw_rera_number", "raw_data", "data_source",
]

_INSERT_SQL = (
    f"INSERT INTO listings ({', '.join(_INSERT_COLUMNS)}) "
    f"VALUES ({', '.join(f':{c}' for c in _INSERT_COLUMNS)})"
)


def _insert_listings(conn, listings: list[dict]) -> int:
    """Insert listings with SAVEPOINT isolation so one failure doesn't abort the batch.

    Uses SQLAlchemy SAVEPOINT/ROLLBACK pattern documented in KILO_BRIEF.md.
    """
    inserted = 0
    errors = 0
    for i, listing in enumerate(listings):
        row = {c: listing.get(c) for c in _INSERT_COLUMNS}
        sp = f"sp_seed_{i}"
        conn.execute(text(f"SAVEPOINT {sp}"))
        try:
            conn.execute(text(_INSERT_SQL), row)
            conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
            inserted += 1
        except Exception as exc:
            conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
            conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
            logger.warning("[SeedListings] Skipped {}/{}: {}", listing.get("locality", "?"), listing.get("source_listing_id", "?"), exc)
            errors += 1
    if errors:
        logger.warning("[SeedListings] {} insert(s) failed out of {}", errors, len(listings))
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Generate and insert seed listing data for RE_OS markets.")
    parser.add_argument("--markets", nargs="*", default=list(MARKETS.keys()),
                        help="Markets to seed (default: all)")
    parser.add_argument("--minimum", type=int, default=30,
                        help="Minimum listings per market (default: 30)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducible generation (default: 42)")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing seed_estimated listings before inserting")
    args = parser.parse_args()

    random.seed(args.seed)
    selected_markets = {k: v for k, v in MARKETS.items() if k in args.markets}
    if not selected_markets:
        logger.error("[SeedListings] No valid markets specified. Choose from: {}", list(MARKETS.keys()))
        return

    engine = get_engine()

    with engine.begin() as conn:
        deleted = 0
        if args.force:
            result = conn.execute(text("DELETE FROM listings WHERE data_source = 'seed_estimated'"))
            deleted = result.rowcount
            logger.info("[SeedListings] Deleted {} existing seed_estimated listings", deleted)

        all_listings = {}
        for market_name, market_config in selected_markets.items():
            all_listings[market_name] = generate_listings(market_name, market_config, args.seed, args.minimum)
            logger.info("[SeedListings] {}: {} listings generated", market_name, len(all_listings[market_name]))

        total_inserted = 0
        for market_name, listings in all_listings.items():
            inserted = _insert_listings(conn, listings)
            total_inserted += inserted

        logger.info("[SeedListings] Inserted {} total listings ({} markets)", total_inserted, len(selected_markets))

    with engine.connect() as conn:
        for market_name, market_config in selected_markets.items():
            cnt = conn.execute(
                text("SELECT COUNT(*) FROM listings WHERE micro_market_id = :mid AND data_source = 'seed_estimated'"),
                {"mid": market_config["id"]},
            ).scalar()
            logger.info("[SeedListings] {}: {} seed listings in DB", market_name, cnt)
            if cnt < args.minimum:
                logger.warning("[SeedListings] {} has {} listings (below minimum {})", market_name, cnt, args.minimum)


if __name__ == "__main__":
    logger.add(lambda msg: print(msg, end=""), format="{message}", level="INFO")
    main()
