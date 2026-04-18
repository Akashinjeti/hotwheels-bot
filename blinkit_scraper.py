"""
blinkit_scraper.py
──────────────────
Scrapes Blinkit for Hot Wheels products using Playwright network interception.

Strategy (in priority order):
  1. Intercept XHR/fetch responses matching Blinkit's search/product API paths
  2. Parse JSON to extract availability, price, name, product_id
  3. Fallback: DOM scraping if API shapes change

Blinkit API patterns observed (may evolve — always verify with DevTools):
  • Search  : /v5/search/?q=...
  • Listing : /v6/listings/page/...
  • Product : /v1/products/{id}/
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import Page, Route, Response, BrowserContext
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────

BLINKIT_BASE   = "https://blinkit.com"
SEARCH_URL     = f"{BLINKIT_BASE}/s/?q={{query}}"
SEARCH_QUERY   = os.getenv("SEARCH_QUERY", "Hot Wheels")
DELIVERY_ADDR  = os.getenv("DELIVERY_ADDRESS", "Regal Vistas Co Living, Madhapur, 500081")
DELIVERY_LAT   = float(os.getenv("DELIVERY_LAT", "17.4485"))
DELIVERY_LNG   = float(os.getenv("DELIVERY_LNG", "78.3908"))

# API path fragments to intercept
API_PATTERNS   = [
    "/v5/search",
    "/v6/search",
    "/v4/search",
    "/listings",
    "/v1/products",
    "/v2/products",
    "api/v",          # generic fallback
]

# ── main scraper ──────────────────────────────────────────────────────────────

class BlinkitScraper:
    def __init__(self, context: BrowserContext) -> None:
        self._context = context
        self._captured: list[dict[str, Any]] = []
        self._page: Page | None = None

    async def __aenter__(self) -> "BlinkitScraper":
        self._page = await self._context.new_page()
        await self._setup_interception()
        return self

    async def __aexit__(self, *_) -> None:
        if self._page:
            await self._page.close()

    # ── public ────────────────────────────────────────────────────────────────

    async def search(self, query: str = SEARCH_QUERY) -> list[dict[str, Any]]:
        """Full search pipeline: set location → open search → collect products."""
        assert self._page is not None
        self._captured.clear()

        url = SEARCH_URL.format(query=quote_plus(query))
        logger.info("🔍  Navigating to: %s", url)

        try:
            await self._page.goto(url, wait_until="networkidle", timeout=30_000)
        except Exception as exc:
            logger.warning("Navigation timeout (will still process captured data): %s", exc)

        # Give late XHR responses a chance to arrive
        await asyncio.sleep(random.uniform(2, 4))

        # Location banner / permission popup handling
        await self._handle_popups()

        # Try to set location if not already set
        await self._ensure_location()

        # Additional scroll to trigger lazy-load XHR
        await self._scroll_page()
        await asyncio.sleep(random.uniform(1.5, 3))

        products = self._captured.copy()

        if not products:
            logger.warning("API interception yielded 0 products — falling back to DOM")
            products = await self._dom_fallback(query)

        logger.info("📦  Total raw products collected: %d", len(products))
        return products

    # ── network interception ──────────────────────────────────────────────────

    async def _setup_interception(self) -> None:
        assert self._page is not None

        async def on_response(response: Response) -> None:
            url = response.url
            if not any(p in url for p in API_PATTERNS):
                return
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                body = await response.json()
                products = self._parse_api_response(body, url)
                if products:
                    logger.debug("🌐  %d products from %s", len(products), url[:80])
                    self._captured.extend(products)
            except Exception as exc:
                logger.debug("Response parse error (%s): %s", url[:60], exc)

        self._page.on("response", on_response)

    def _parse_api_response(
        self, body: Any, source_url: str
    ) -> list[dict[str, Any]]:
        """
        Try multiple known Blinkit JSON shapes.
        Blinkit has refactored their API schema several times;
        we check several paths defensively.
        """
        results: list[dict[str, Any]] = []

        # ── Shape A: { objects: [ { type: "product", product: {...} } ] }
        objects = _deep_get(body, "objects") or []
        for obj in objects:
            p = obj.get("product") or obj
            parsed = self._extract_product(p)
            if parsed:
                results.append(parsed)

        # ── Shape B: { products: [...] }
        if not results:
            for p in _deep_get(body, "products") or []:
                parsed = self._extract_product(p)
                if parsed:
                    results.append(parsed)

        # ── Shape C: nested inside "data" key
        if not results:
            data = body.get("data", {})
            if isinstance(data, dict):
                for key in ("products", "results", "items"):
                    for p in data.get(key) or []:
                        parsed = self._extract_product(p)
                        if parsed:
                            results.append(parsed)

        # ── Shape D: flat list at root
        if not results and isinstance(body, list):
            for p in body:
                parsed = self._extract_product(p)
                if parsed:
                    results.append(parsed)

        return results

    @staticmethod
    def _extract_product(p: dict) -> dict | None:
        """Map a raw API product object to our normalised schema."""
        if not isinstance(p, dict):
            return None

        name = (
            p.get("name")
            or p.get("product_name")
            or p.get("title")
            or ""
        )
        if not name:
            return None

        # Only keep Hot Wheels items
        if "hot wheels" not in name.lower() and "hotwheels" not in name.lower():
            # Some listings include generic toys; skip non-HW items
            pass  # we'll let filter.py decide — include all for now

        price_raw = (
            p.get("price")
            or p.get("mrp")
            or p.get("sale_price")
            or p.get("selling_price")
            or 0
        )
        try:
            price = float(price_raw) / 100 if float(price_raw) > 10_000 else float(price_raw)
        except (TypeError, ValueError):
            price = 0.0

        # Stock detection — check multiple flag names
        in_stock = (
            p.get("in_stock")
            or p.get("is_available")
            or p.get("available")
            or p.get("inventory_quantity", 0) > 0
            or p.get("stock", 0) > 0
        )
        # Some APIs use strings
        if isinstance(in_stock, str):
            in_stock = in_stock.lower() in ("true", "1", "yes", "available")
        in_stock = bool(in_stock)

        product_id = str(
            p.get("id")
            or p.get("product_id")
            or p.get("sku")
            or p.get("item_id")
            or ""
        )

        # Build URL
        slug = p.get("slug") or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        url = f"{BLINKIT_BASE}/prn/{slug}/prid/{product_id}" if product_id else BLINKIT_BASE

        return {
            "name":       name,
            "price":      price,
            "in_stock":   in_stock,
            "product_id": product_id,
            "url":        url,
            "raw":        p,         # kept for debugging; remove in production
        }

    # ── location helpers ──────────────────────────────────────────────────────

    async def _ensure_location(self) -> None:
        """Attempt to set/confirm delivery location via UI if needed."""
        assert self._page is not None
        page = self._page

        # Try to detect if location is already set
        try:
            loc_text = await page.locator(
                "[data-testid='location-widget'], "
                ".LocationBar__Address, "
                ".location-text, "
                "[class*='location']"
            ).first.inner_text(timeout=3000)
            if "500081" in loc_text or "Madhapur" in loc_text:
                logger.info("📍  Location already set correctly")
                return
        except Exception:
            pass

        logger.info("📍  Attempting to set delivery location …")
        try:
            # Click location selector
            await page.locator(
                "[data-testid='location-widget'], "
                ".LocationBar, "
                "[class*='location-selector'], "
                "[class*='LocationBar']"
            ).first.click(timeout=5000)
            await asyncio.sleep(1)

            # Type address into search field
            inp = page.locator("input[placeholder*='location'], input[placeholder*='address'], input[placeholder*='pincode']")
            await inp.first.fill(DELIVERY_ADDR[:20], timeout=5000)
            await asyncio.sleep(1.5)

            # Click first suggestion
            suggestion = page.locator("[data-testid*='suggestion'], [class*='suggestion'], [class*='Suggestion']")
            if await suggestion.count() > 0:
                await suggestion.first.click(timeout=3000)
                await asyncio.sleep(2)
                logger.info("✅  Location set via UI")
        except Exception as exc:
            logger.warning("Location UI interaction failed: %s", exc)

    # ── popup handling ─────────────────────────────────────────────────────────

    async def _handle_popups(self) -> None:
        assert self._page is not None
        page = self._page

        dismiss_selectors = [
            "button[aria-label='Close']",
            "[data-testid='modal-close']",
            "button:has-text('Not Now')",
            "button:has-text('Maybe Later')",
            "button:has-text('Skip')",
            "[class*='closeButton']",
            "[class*='CloseButton']",
        ]
        for sel in dismiss_selectors:
            try:
                btn = page.locator(sel)
                if await btn.count() > 0:
                    await btn.first.click(timeout=2000)
                    await asyncio.sleep(0.5)
            except Exception:
                pass

    # ── scroll helper ─────────────────────────────────────────────────────────

    async def _scroll_page(self) -> None:
        assert self._page is not None
        page = self._page
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
            await asyncio.sleep(random.uniform(0.4, 0.9))

    # ── DOM fallback ──────────────────────────────────────────────────────────

    async def _dom_fallback(self, query: str) -> list[dict[str, Any]]:
        """
        Last-resort DOM scraping.
        Selectors are brittle but serve as a safety net.
        """
        assert self._page is not None
        page = self._page
        products: list[dict[str, Any]] = []

        try:
            # Generic product card selectors (update as Blinkit UI evolves)
            cards = await page.locator(
                "[data-testid='product-card'], "
                "[class*='ProductCard'], "
                "[class*='product-card'], "
                "[class*='Product__Info']"
            ).all()

            for card in cards:
                try:
                    name  = await card.locator(
                        "[class*='name'], [class*='Name'], [data-testid*='name']"
                    ).first.inner_text(timeout=1000)
                    price_text = await card.locator(
                        "[class*='price'], [class*='Price'], [data-testid*='price']"
                    ).first.inner_text(timeout=1000)
                    price = float(re.sub(r"[^\d.]", "", price_text) or "0")

                    out_of_stock_el = await card.locator(
                        "[class*='outofstock'], [class*='OutOfStock'], "
                        "[class*='unavailable'], :has-text('Out of Stock')"
                    ).count()
                    in_stock = out_of_stock_el == 0

                    products.append({
                        "name":       name.strip(),
                        "price":      price,
                        "in_stock":   in_stock,
                        "product_id": "",
                        "url":        BLINKIT_BASE,
                    })
                except Exception:
                    continue
        except Exception as exc:
            logger.error("DOM fallback failed: %s", exc)

        logger.info("DOM fallback found %d products", len(products))
        return products


# ── util ──────────────────────────────────────────────────────────────────────

def _deep_get(obj: Any, key: str) -> Any:
    """Return obj[key] whether obj is a dict or has it nested inside 'data'."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        if "data" in obj and isinstance(obj["data"], dict):
            return obj["data"].get(key)
    return None
