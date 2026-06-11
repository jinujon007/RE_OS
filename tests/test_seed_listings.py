import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


class TestSeedListingsGenerator:
    def test_generate_listings_returns_minimum_count(self):
        from database.seed_listings import generate_listings

        market_config = {
            "id": "0a10553b-cc39-4ca0-ae83-5fc1643b912c",
            "psf_range": (6000, 12000),
        }
        listings = generate_listings("Yelahanka", market_config, seed=42, minimum=30)
        assert len(listings) >= 30

    def test_generate_listings_default_minimum_is_30(self):
        from database.seed_listings import generate_listings

        market_config = {
            "id": "f796fadf-6fcc-46ae-b5f8-6af2a9784468",
            "psf_range": (4000, 8000),
        }
        listings = generate_listings("Devanahalli", market_config, seed=42)
        assert len(listings) >= 30

    def test_generate_listings_market_not_in_templates(self):
        from database.seed_listings import generate_listings

        market_config = {"id": "fake-uuid", "psf_range": (5000, 10000)}
        with pytest.raises(KeyError):
            generate_listings("NonExistentMarket", market_config, seed=42, minimum=30)

    def test_listing_has_required_fields(self):
        from database.seed_listings import generate_listings

        market_config = {
            "id": "c7b25515-c290-49b5-bb04-82378dc6b1b8",
            "psf_range": (8000, 15000),
        }
        listings = generate_listings("Hebbal", market_config, seed=42, minimum=30)
        required = {
            "id",
            "source",
            "micro_market_id",
            "data_source",
            "price_psf",
            "locality",
        }
        for listing in listings[:5]:
            missing = required - set(listing.keys())
            assert not missing, f"Listing missing fields: {missing}"

    def test_source_equals_data_source(self):
        from database.seed_listings import generate_listings

        market_config = {
            "id": "0a10553b-cc39-4ca0-ae83-5fc1643b912c",
            "psf_range": (6000, 12000),
        }
        listings = generate_listings("Yelahanka", market_config, seed=42, minimum=5)
        for listing in listings:
            assert listing["source"] == "seed_estimated", (
                f"source={listing['source']} should be seed_estimated"
            )
            assert listing["data_source"] == "seed_estimated"

    def test_price_psf_within_range(self):
        from database.seed_listings import generate_listings

        market_config = {
            "id": "0a10553b-cc39-4ca0-ae83-5fc1643b912c",
            "psf_range": (6000, 12000),
        }
        listings = generate_listings("Yelahanka", market_config, seed=42, minimum=30)
        psf_min, psf_max = market_config["psf_range"]
        for listing in listings:
            assert psf_min <= listing["price_psf"] <= psf_max, (
                f"PSF {listing['price_psf']} outside [{psf_min}, {psf_max}]"
            )

    def test_deterministic_seed_produces_same_output(self):
        from database.seed_listings import generate_listings

        mc = {"id": "test-uuid", "psf_range": (5000, 10000)}
        with patch(
            "database.seed_listings.PROJECT_TEMPLATES",
            {
                "TestMarket": [("DevA", ["Project X"]), ("DevB", ["Project Y"])],
            },
        ):
            batch1 = generate_listings("TestMarket", mc, seed=99, minimum=2)
            batch2 = generate_listings("TestMarket", mc, seed=99, minimum=2)
            for a, b in zip(batch1, batch2):
                assert a["price_psf"] == b["price_psf"], (
                    "Same seed should produce same PSF"
                )
                assert a["bhk_config"] == b["bhk_config"], (
                    "Same seed should produce same BHK"
                )

    def test_different_seed_produces_different_output(self):
        from database.seed_listings import generate_listings

        mc = {"id": "test-uuid", "psf_range": (5000, 10000)}
        with patch(
            "database.seed_listings.PROJECT_TEMPLATES",
            {
                "TestMarket": [("DevA", ["Project X"])],
            },
        ):
            batch1 = generate_listings("TestMarket", mc, seed=42, minimum=1)
            batch2 = generate_listings("TestMarket", mc, seed=99, minimum=1)
            assert batch1[0]["price_psf"] != batch2[0]["price_psf"], (
                "Different seeds should (likely) produce different PSF"
            )


class TestSeedListingsInsert:
    def test_insert_listings_none_skipped(self):
        from database.seed_listings import _insert_listings

        mock_conn = MagicMock()
        listings = [
            {"id": "1", "source": "seed_estimated", "locality": "Test"},
            {"id": "2", "source": "seed_estimated", "locality": "Test"},
        ]
        for l in listings:
            for c in [
                "source_listing_id",
                "source_url",
                "micro_market_id",
                "rera_project_id",
                "property_type",
                "transaction_type",
                "bhk_config",
                "carpet_area_sqft",
                "built_up_area_sqft",
                "super_built_up_sqft",
                "plot_area_sqft",
                "listed_price",
                "price_psf",
                "monthly_rent",
                "security_deposit",
                "deposit_months",
                "address",
                "listed_at",
                "days_on_market",
                "is_new_launch",
                "is_rera_registered",
                "raw_rera_number",
                "raw_data",
                "data_source",
                "is_active",
            ]:
                l.setdefault(c, None)
        result = _insert_listings(mock_conn, listings)
        assert result == 2
        # SAVEPOINT pattern: 3 calls per listing (SAVEPOINT + INSERT + RELEASE)
        assert mock_conn.execute.call_count >= 2
