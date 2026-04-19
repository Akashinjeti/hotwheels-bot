"""
blinkit_scraper.py  (v3 — location injected via JS + API headers)
──────────────────────────────────────────────────────────────────
Sets location directly in browser storage before page load,
bypassing the UI location selector entirely.
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

from playwright.async_api import Page, Response, BrowserContext
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BLINKIT_BASE  = "https://blinkit.com"
SEARCH_URL    = f"{BLINKIT_BASE}/s/?q={{query}}"
SEARCH_QUERY  = os.getenv("SEARCH_QUERY", "Hot Wheels")
DELIVERY_LAT  = float(os.getenv("DELIVERY_LAT", "17.4485"))
DELIVERY_LNG  = float(os.getenv("DELIVERY_LNG", "78.3908"))

API_PATTERNS = [
    "/v5/search", "/v6/search", "/v4/search",
    "/v3/search", "/v2/search",
    "/listings", "/v1/products", "/v2/products",
    "api/v",
]

# Location JS injected before every page load
LOCATION_SCRIPT = f"""
(function() {{
    // Blinkit stores location in multiple localStorage keys
    const lat = {DELIVERY_LAT};
    const lng = {DELIVERY_LNG};
    const loc = JSON.stringify({{lat, lng, address: "Madhapur, Hyderabad, 500081"}});

    const keys = [
        'userLocation', 'gr_1', 'location', 'selectedLocation',
        'deliveryLocation', 'bl_location', 'user_location',
        'latlng', 'coordinates'
    ];
    keys.forEach(k => {{ try {{ localStorage.setItem(k, loc); }} catch(e) {{}} }});

    // Also set as individual keys some versions use
    try {{ localStorage.setItem('lat', String(lat)); }} catch(e) {{}}
    try {{ localStorage.setItem('lng', String(lng)); }} catch(e) {{}}
    try {{ localStorage.setItem('userLat', String(lat)); }} catch(e) {{}}
    try {{ localStorage.setItem('userLng', String(lng)); }} catch(e) {{}}

    // Override geolocation API
    Object.defineProperty(navigator, 'geolocation', {{
        value: {{
            getCurrentPosition: (success) => success({{
                coords: {{ latitude: lat, longitude: lng, accuracy: 10 }}
            }}),
            watchPosition: (success) => success({{
                coords: {{ latitude: lat, longitude: lng, accuracy: 10 }}
            }})
        }}
    }});
}})();
"""


class BlinkitScraper:
    def __init__(self, context: BrowserContext) -> None:
        self._context = context
        self._captured: list[dict[str, Any]] = []
        self._page: Page | None = None

    async def __aenter__(self) -> "BlinkitScraper":
        self._page = await self._context.new_page()
        # Inject location script before ANY page script runs
        await self._page.add_init_script(LOCATION_SCRIPT)
        await self._setup_interception()
        return self

    async def __aexit__(self, *_) -> None:
        if self._page:
            await self._page.close()

    async def search(self, query: str = SEARCH_QUERY) -> list[dict[str, Any]]:
        assert self._page is not None
        self._captured.clear()

        url = SEARCH_URL.format(query=quote_plus(query))
        logger.info("🔍  Navigating to: %s", url)

        try:
            await self._page.goto(url, wait_until="networkidle", timeout=35_000)
        except Exception as exc:
            logger.warning("Navigation timeout (continuing): %s", exc)

        await asyncio.sleep(random.uniform(2, 4))
        await self._handle_popups()

        # Scroll to trigger lazy-loaded API calls
        await self._scroll_page()
        await asyncio.sleep(random.uniform(1.5, 3))

        # Try a second scroll pass
        await self._scroll_page()
        await asyncio.sleep(random.uniform(1, 2))

        products = self._captured.copy()

        if not products:
            logger.warning("API interception yielded 0 products — falling back to DOM")
            products = await self._dom_fallback()

        logger.info("📦  Total raw products collected: %d", len(products))
        return products

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

    def _parse_api_response(self, body: Any, source_url: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        # Shape A: { objects: [...] }
        for obj in (_deep_get(body, "objects") or []):
            p = obj.get("product") or obj
            parsed = self._extract_product(p)
            if parsed:
                results.append(parsed)

        # Shape B: { products: [...] }
        if not results:
            for p in (_deep_get(body, "products") or []):
                parsed = self._extract_product(p)
                if parsed:
                    results.append(parsed)

        # Shape C: nested data key
        if not results:
            data = body.get("data", {}) if isinstance(body, dict) else {}
            for key in ("products", "results", "items", "objects"):
                for p in (data.get(key) or []):
                    parsed = self._extract_product(p)
                    if parsed:
                        results.append(parsed)

        # Shape D: flat list
        if not results and isinstance(body, list):
            for p in body:
                parsed = self._extract_product(p)
                if parsed:
                    results.append(parsed)

        return results

    @staticmethod
    def _extract_product(p: dict) -> dict | None:
        if not isinstance(p, dict):
            return None

        name = (p.get("name") or p.get("product_name") or p.get("title") or "").strip()
        if not name:
            return None

        price_raw = (
            p.get("price") or p.get("mrp") or
            p.get("sale_price") or p.get("selling_price") or 0
        )
        try:
            price = float(price_raw)
            if price > 10_000:
                price /= 100
        except (TypeError, ValueError):
            price = 0.0

        in_stock = (
            p.get("in_stock") or p.get("is_available") or
            p.get("available") or
            (p.get("inventory_quantity", 0) or 0) > 0 or
            (p.get("stock", 0) or 0) > 0
        )
        if isinstance(in_stock, str):
            in_stock = in_stock.lower() in ("true", "1", "yes", "available")
        in_stock = bool(in_stock)

        product_id = str(
            p.get("id") or p.get("product_id") or
            p.get("sku") or p.get("item_id") or ""
        )

        slug = p.get("slug") or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        url = f"{BLINKIT_BASE}/prn/{slug}/prid/{product_id}" if product_id else BLINKIT_BASE

        return {
            "name": name, "price": price,
            "in_stock": in_stock, "product_id": product_id,
            "url": url,
        }

    async def _handle_popups(self) -> None:
        assert self._page is not None
        for sel in [
            "button[aria-label='Close']", "[data-testid='modal-close']",
            "button:has-text('Not Now')", "button:has-text('Maybe Later')",
            "button:has-text('Skip')", "[class*='closeButton']",
        ]:
            try:
                btn = self._page.locator(sel)
                if await btn.count() > 0:
                    await btn.first.click(timeout=2000)
                    await asyncio.sleep(0.5)
            except Exception:
                pass

    async def _scroll_page(self) -> None:
        assert self._page is not None
        for _ in range(5):
            await self._page.evaluate("window.scrollBy(0, window.innerHeight * 0.9)")
            await asyncio.sleep(random.uniform(0.4, 0.8))
        await self._page.evaluate("window.scrollTo(0, 0)")

    async def _dom_fallback(self) -> list[dict[str, Any]]:
        assert self._page is not None
        products: list[dict[str, Any]] = []
        try:
            cards = await self._page.locator(
                "[data-testid='product-card'], [class*='ProductCard'], "
                "[class*='product-card'], [class*='Product__Info']"
            ).all()
            for card in cards:
                try:
                    name = await card.locator(
                        "[class*='name'], [class*='Name']"
                    ).first.inner_text(timeout=1000)
                    price_text = await card.locator(
                        "[class*='price'], [class*='Price']"
                    ).first.inner_text(timeout=1000)
                    price = float(re.sub(r"[^\d.]", "", price_text) or "0")
                    oos = await card.locator(
                        "[class*='outofstock'], :has-text('Out of Stock')"
                    ).count()
                    products.append({
                        "name": name.strip(), "price": price,
                        "in_stock": oos == 0, "product_id": "", "url": BLINKIT_BASE,
                    })
                except Exception:
                    continue
        except Exception as exc:
            logger.error("DOM fallback error: %s", exc)
        logger.info("DOM fallback found %d products", len(products))
        return products


def _deep_get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        if "data" in obj and isinstance(obj["data"], dict):
            return obj["data"].get(key)
    return None
