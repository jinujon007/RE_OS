"""
RE_OS — Property Listings Scraper (DEPRECATED)
────────────────────────────────────────────────
Superseded by portal_scout.py (Sprint 79 — 2026-06-08).
Retained for reference only. Do not re-add to crew.
"""

DEPRECATED = True

import requests
from bs4 import BeautifulSoup
import json
import time
import re
import argparse
from datetime import datetime
from loguru import logger


class ListingsScraper:
    """
    Scrapes property listings from public portals.
    Uses 99acres as primary source — has the most Bengaluru inventory.
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    # 99acres locality slug mapping
    LOCALITY_SLUGS = {
        "Yelahanka": "yelahanka-bangalore",
        "Devanahalli": "devanahalli-bangalore",
        "Hebbal": "hebbal-bangalore",
        "Jakkur": "jakkur-bangalore",
        "Thanisandra": "thanisandra-bangalore",
        "Whitefield": "whitefield-bangalore",
        "Sarjapur Road": "sarjapur-road-bangalore",
        "Electronic City": "electronic-city-bangalore",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def scrape_market(self, market_name: str) -> list[dict]:
        """
        Main entry — scrape sale + rent listings for a market.
        Returns list of listing dicts.
        """
        logger.info(f"Starting listings scrape for: {market_name}")
        listings = []

        # Try 99acres
        sale_listings = self._scrape_99acres(market_name, transaction_type="sale")
        rent_listings = self._scrape_99acres(market_name, transaction_type="rent")
        listings.extend(sale_listings)
        listings.extend(rent_listings)

        if not listings:
            logger.warning("  No listings from 99acres — trying MagicBricks")
            listings = self._scrape_magicbricks(market_name)

        if not listings:
            logger.warning("  All scrapers returned empty — using structured fallback")
            listings = self._fallback_listings(market_name)

        logger.info(f"  Total listings collected: {len(listings)}")
        return listings

    def _scrape_99acres(
        self, market_name: str, transaction_type: str = "sale"
    ) -> list[dict]:
        """Scrape 99acres search results for a locality."""
        listings = []
        slug = self.LOCALITY_SLUGS.get(
            market_name, market_name.lower().replace(" ", "-") + "-bangalore"
        )

        try:
            # 99acres URL pattern for locality search
            if transaction_type == "sale":
                url = f"https://www.99acres.com/property-for-sale-in-{slug}-ffid"
            else:
                url = f"https://www.99acres.com/property-for-rent-in-{slug}-ffid"

            response = self.session.get(url, timeout=20)
            time.sleep(1)

            if response.status_code != 200:
                logger.warning(
                    f"  99acres {transaction_type} returned HTTP {response.status_code}"
                )
                return []

            soup = BeautifulSoup(response.text, "lxml")

            # 99acres listing cards — class names change, so try multiple patterns
            listing_cards = (
                soup.find_all(
                    "div", class_=re.compile(r"srpTuple|listingCard|propertyCard", re.I)
                )
                or soup.find_all(
                    "article", class_=re.compile(r"listing|property", re.I)
                )
                or soup.find_all("div", attrs={"data-id": True})
            )

            for card in listing_cards[:30]:  # cap at 30 per type
                listing = self._parse_99acres_card(card, market_name, transaction_type)
                if listing:
                    listings.append(listing)

            logger.info(f"  99acres {transaction_type}: {len(listings)} listings")

        except requests.exceptions.RequestException as e:
            logger.warning(f"  99acres request failed: {e}")
        except Exception as e:
            logger.debug(f"  99acres parse error: {e}")

        return listings

    def _parse_99acres_card(
        self, card, market_name: str, transaction_type: str
    ) -> dict | None:
        """Parse a 99acres listing card."""
        try:
            text = card.get_text(separator=" ", strip=True)

            # Extract price
            price_raw = ""
            price_match = re.search(r"₹\s*[\d,.]+\s*(?:Cr|L|Lac|Lakh|K)?", text, re.I)
            if price_match:
                price_raw = price_match.group()

            # Extract area
            area_match = re.search(r"(\d[\d,]*)\s*(?:sq\.?\s*ft|sqft)", text, re.I)
            area_sqft = int(area_match.group(1).replace(",", "")) if area_match else 0

            # Extract BHK
            bhk_match = re.search(r"(\d)\s*BHK", text, re.I)
            bhk = f"{bhk_match.group(1)} BHK" if bhk_match else "Unknown"

            if not price_raw:
                return None

            return {
                "price_display": price_raw,
                "price_numeric": self._parse_price(price_raw),
                "area_sqft": area_sqft,
                "bhk_config": bhk,
                "transaction_type": transaction_type,
                "locality": market_name,
                "source": "99acres",
                "scraped_at": datetime.now().isoformat(),
            }
        except Exception:
            return None

    def _scrape_magicbricks(self, market_name: str) -> list[dict]:
        """Fallback: try MagicBricks."""
        listings = []
        try:
            locality_encoded = market_name.replace(" ", "%20")
            url = f"https://www.magicbricks.com/property-for-sale/residential-real-estate?proptype=Multistorey-Apartment,Builder-Floor-Apartment,Penthouse,Studio-Apartment&cityName=Bangalore&Area={locality_encoded}"

            response = self.session.get(url, timeout=20)
            time.sleep(1)

            if response.status_code != 200:
                return []

            soup = BeautifulSoup(response.text, "lxml")
            cards = soup.find_all(
                "div", class_=re.compile(r"mb-srp|listingCard|propCard", re.I)
            )

            for card in cards[:20]:
                text = card.get_text(separator=" ", strip=True)
                price_match = re.search(r"₹\s*[\d,.]+\s*(?:Cr|L|Lac)?", text, re.I)
                area_match = re.search(r"(\d[\d,]*)\s*sq\.?\s*ft", text, re.I)
                bhk_match = re.search(r"(\d)\s*BHK", text, re.I)

                if price_match:
                    listings.append(
                        {
                            "price_display": price_match.group(),
                            "price_numeric": self._parse_price(price_match.group()),
                            "area_sqft": int(area_match.group(1).replace(",", ""))
                            if area_match
                            else 0,
                            "bhk_config": f"{bhk_match.group(1)} BHK"
                            if bhk_match
                            else "Unknown",
                            "transaction_type": "sale",
                            "locality": market_name,
                            "source": "magicbricks",
                            "scraped_at": datetime.now().isoformat(),
                        }
                    )

        except Exception as e:
            logger.debug(f"  MagicBricks scrape failed: {e}")

        return listings

    def _fallback_listings(self, market_name: str) -> list[dict]:
        """
        Structured fallback when live scraping fails (portal blocking, JS-heavy, etc).
        Returns realistic sample data based on known North Bengaluru market ranges.
        Used so the pipeline can complete an end-to-end run.
        Mark source as 'fallback_sample' so analyst knows data is not live.
        """
        logger.warning(f"  Using fallback sample data for {market_name} listings")

        # North Bengaluru market ranges (realistic as of 2024-2026)
        market_profiles = {
            "Yelahanka": {
                "sale_2bhk_range": (55, 85),  # lakhs
                "sale_3bhk_range": (85, 140),
                "rent_2bhk_range": (18, 28),  # thousands/month
                "rent_3bhk_range": (28, 45),
                "area_2bhk": (950, 1250),
                "area_3bhk": (1350, 1700),
            },
            "Devanahalli": {
                "sale_2bhk_range": (45, 75),
                "sale_3bhk_range": (75, 120),
                "rent_2bhk_range": (15, 22),
                "rent_3bhk_range": (22, 35),
                "area_2bhk": (900, 1200),
                "area_3bhk": (1300, 1600),
            },
        }

        profile = market_profiles.get(market_name, market_profiles["Yelahanka"])
        now = datetime.now().isoformat()
        listings = []

        # Generate 10 representative sale listings
        configs = [
            ("2 BHK", profile["sale_2bhk_range"], profile["area_2bhk"], "sale"),
            ("2 BHK", profile["sale_2bhk_range"], profile["area_2bhk"], "sale"),
            ("3 BHK", profile["sale_3bhk_range"], profile["area_3bhk"], "sale"),
            ("3 BHK", profile["sale_3bhk_range"], profile["area_3bhk"], "sale"),
            ("2 BHK", profile["sale_2bhk_range"], profile["area_2bhk"], "sale"),
            ("3 BHK", profile["sale_3bhk_range"], profile["area_3bhk"], "sale"),
            ("2 BHK", profile["rent_2bhk_range"], profile["area_2bhk"], "rent"),
            ("2 BHK", profile["rent_2bhk_range"], profile["area_2bhk"], "rent"),
            ("3 BHK", profile["rent_3bhk_range"], profile["area_3bhk"], "rent"),
            ("3 BHK", profile["rent_3bhk_range"], profile["area_3bhk"], "rent"),
        ]

        for i, (bhk, price_range, area_range, txn_type) in enumerate(configs):
            import random

            random.seed(i + hash(market_name) % 100)
            price = random.randint(*price_range)
            area = random.randint(*area_range)
            unit = "L" if txn_type == "sale" else "K/mo"
            listings.append(
                {
                    "price_display": f"₹ {price} {unit}",
                    "price_numeric": price * (100000 if txn_type == "sale" else 1000),
                    "area_sqft": area,
                    "bhk_config": bhk,
                    "transaction_type": txn_type,
                    "locality": market_name,
                    "source": "fallback_sample",
                    "note": "Live scraping blocked — sample data for pipeline testing",
                    "scraped_at": now,
                }
            )

        return listings

    def _parse_price(self, price_str: str) -> int:
        """Convert price string like '₹ 85 L' to integer."""
        try:
            s = re.sub(r"[₹,\s]", "", price_str).upper()
            num_match = re.search(r"[\d.]+", s)
            if not num_match:
                return 0
            num = float(num_match.group())
            if "CR" in s:
                return int(num * 10000000)
            elif "L" in s or "LAC" in s or "LAKH" in s:
                return int(num * 100000)
            elif "K" in s:
                return int(num * 1000)
            return int(num)
        except Exception:
            return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Property Listings Scraper")
    parser.add_argument("--market", default="Yelahanka")
    args = parser.parse_args()

    scraper = ListingsScraper()
    listings = scraper.scrape_market(args.market)
    print(f"\nTotal listings: {len(listings)}")
    print(json.dumps(listings[:3], indent=2))
