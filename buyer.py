"""
buyer.py  (v2 — full COD auto-order + address fill + quota tracking)
─────────────────────────────────────────────────────────────────────
Flow per product:
  1. Navigate to product page
  2. Click "Add to Cart"
  3. Open cart / proceed to checkout
  4. Confirm / select saved delivery address
  5. Select "Cash on Delivery"
  6. Click "Place Order"  <- fully automated
  7. Confirm success screen -> record in order_tracker
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from playwright.async_api import BrowserContext, Page, TimeoutError as PWTimeout
from dotenv import load_dotenv

from config        import USER_PROFILE, AUTO_PLACE_ORDER, MAX_RETRIES, CART_COOLDOWN
from notifier      import (
    Product, alert_added_to_cart, alert_checkout_reached, alert_error, alert_info,
)
from order_tracker import record_order

load_dotenv()
logger = logging.getLogger(__name__)

BLINKIT_BASE = "https://blinkit.com"
_cooldown_registry: dict[str, float] = {}

ADD_BTN = [
    "button[data-testid='add-to-cart']",
    "[class*='AddToCart'] button",
    "[class*='add-to-cart'] button",
    "button:has-text('Add')",
    "button:has-text('+')",
    "[data-cy='add-to-cart-btn']",
]

CART_BTN = [
    "a[href*='/checkout']",
    "button[data-testid='checkout-btn']",
    "button:has-text('Proceed to Checkout')",
    "button:has-text('Checkout')",
    "[class*='checkout'] button",
]

CONTINUE_BTN = [
    "button:has-text('Continue')",
    "button:has-text('Confirm')",
    "button:has-text('Proceed')",
    "button[data-testid='continue-btn']",
]

COD_SELECTORS = [
    "label:has-text('Cash on Delivery')",
    "div:has-text('Cash on Delivery') input[type='radio']",
    "[data-testid='cod-option']",
    "label:has-text('COD')",
    "[class*='CashOnDelivery']",
    "input[value='cod']",
    "input[value='COD']",
    "input[value='CASH']",
    "div[data-payment-method='cod']",
    "li:has-text('Cash on Delivery')",
]

PLACE_ORDER_BTN = [
    "button[data-testid='place-order']",
    "button:has-text('Place Order')",
    "button:has-text('Confirm Order')",
    "button:has-text('Pay on Delivery')",
    "[class*='PlaceOrder'] button",
    "button[data-cy='place-order']",
]

ADDRESS_CONFIRM_BTN = [
    "button:has-text('Deliver Here')",
    "button:has-text('Confirm Address')",
    "button:has-text('Use This Address')",
    "[data-testid='confirm-address']",
    "button:has-text('Continue')",
]

SUCCESS_INDICATORS = [
    "[data-testid='order-success']",
    "[class*='OrderSuccess']",
    "[class*='order-confirmed']",
    "h1:has-text('Order Placed')",
    "h2:has-text('Order Placed')",
    ":has-text('Order Confirmed')",
    ":has-text('Your order has been placed')",
]


class BlinkitBuyer:
    def __init__(self, context: BrowserContext) -> None:
        self._context = context

    async def buy(self, product: dict[str, Any]) -> bool:
        pid  = product.get("product_id", "")
        name = product.get("name", "unknown")

        if self._on_cooldown(pid):
            logger.info("Cooldown active for %s", name)
            return False

        page = await self._context.new_page()
        try:
            return await self._run_flow(page, product)
        except Exception as exc:
            logger.error("buy() fatal: %s", exc)
            await alert_error(f"buy({name})", exc)
            return False
        finally:
            await page.close()

    async def _run_flow(self, page: Page, product: dict) -> bool:
        pobj = Product(
            name=product["name"], price=product["price"],
            product_id=product.get("product_id", ""), url=product["url"],
        )
        target = product.get("_target", {})

        added = await self._add_to_cart(page, pobj)
        if not added:
            return False

        _cooldown_registry[pobj.product_id] = time.time()
        await alert_added_to_cart(pobj)
        await self._open_checkout(page)
        await self._confirm_address(page)
        await self._select_cod(page)
        placed = await self._place_order(page, pobj)

        if placed:
            record_order(target.get("id", pobj.product_id))
            await alert_info(
                f"🎉 Order placed!\n<b>{pobj.name}</b>  ₹{pobj.price:.0f}\n"
                f"Payment: Cash on Delivery 💵"
            )
        return placed

    async def _add_to_cart(self, page: Page, product: Product) -> bool:
        logger.info("Adding to cart: %s", product.name)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await page.goto(product.url, wait_until="domcontentloaded", timeout=25_000)
                await _delay(1.0, 2.0)
                await _dismiss_popups(page)
                for sel in ADD_BTN:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=2500):
                            await btn.scroll_into_view_if_needed()
                            await _delay(0.3, 0.7)
                            await btn.click(timeout=5000)
                            logger.info("Add to Cart clicked [%s]", sel)
                            await _delay(1.0, 2.0)
                            return True
                    except Exception:
                        continue
                logger.warning("Attempt %d: button not found", attempt)
            except Exception as exc:
                logger.warning("Attempt %d: %s", attempt, exc)
            await _delay(2 * attempt, 4 * attempt)

        logger.error("Could not add %s after %d attempts", product.name, MAX_RETRIES)
        return False

    async def _open_checkout(self, page: Page) -> None:
        logger.info("Opening checkout …")
        try:
            await page.goto(f"{BLINKIT_BASE}/checkout/", wait_until="domcontentloaded", timeout=20_000)
            await _delay(1.5, 2.5)
            await _dismiss_popups(page)
        except Exception as exc:
            logger.warning("checkout nav: %s", exc)
        for sel in CART_BTN:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click(timeout=5000)
                    await _delay(1.5, 2.5)
                    logger.info("Checkout button clicked [%s]", sel)
                    break
            except Exception:
                continue

    async def _confirm_address(self, page: Page) -> None:
        logger.info("Confirming address …")
        await _delay(1.0, 2.0)
        await _dismiss_popups(page)
        await _fill(page, "input[type='tel']", USER_PROFILE["phone"])
        await _fill(page, "input[placeholder*='phone']", USER_PROFILE["phone"])
        await _fill(page, "input[placeholder*='mobile']", USER_PROFILE["phone"])
        await _fill(page, "input[placeholder*='name']", USER_PROFILE["name"])
        for sel in ADDRESS_CONFIRM_BTN:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2500):
                    await btn.click(timeout=5000)
                    await _delay(1.0, 2.0)
                    logger.info("Address confirmed [%s]", sel)
                    return
            except Exception:
                continue

    async def _select_cod(self, page: Page) -> None:
        logger.info("Selecting Cash on Delivery …")
        await _delay(1.0, 2.0)
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 400)")
            await _delay(0.3, 0.6)
        for sel in COD_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    await el.scroll_into_view_if_needed()
                    await _delay(0.3, 0.6)
                    await el.click(timeout=5000)
                    logger.info("COD selected [%s]", sel)
                    await _delay(0.8, 1.5)
                    return
            except Exception:
                continue
        logger.warning("COD option not found — may be default or layout changed")

    async def _place_order(self, page: Page, product: Product) -> bool:
        await alert_checkout_reached(product)
        if not AUTO_PLACE_ORDER:
            logger.info("AUTO_PLACE_ORDER=False — stopping before final confirm")
            return False

        logger.info("Placing order …")
        await _delay(0.5, 1.2)
        for sel in PLACE_ORDER_BTN:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=3000):
                    await btn.scroll_into_view_if_needed()
                    await _delay(0.4, 0.8)
                    await btn.click(timeout=8000)
                    logger.info("Place Order clicked [%s]", sel)
                    await _delay(2.0, 4.0)
                    if await self._is_success(page):
                        return True
                    if any(kw in page.url for kw in ("success", "confirmed", "placed", "track")):
                        return True
            except Exception as exc:
                logger.warning("Place Order attempt: %s", exc)

        logger.error("Place Order button not found or order failed")
        return False

    @staticmethod
    async def _is_success(page: Page) -> bool:
        for sel in SUCCESS_INDICATORS:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    @staticmethod
    def _on_cooldown(pid: str) -> bool:
        if not pid:
            return False
        return (time.time() - _cooldown_registry.get(pid, 0)) < CART_COOLDOWN


async def _delay(lo: float, hi: float) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


async def _dismiss_popups(page: Page) -> None:
    for sel in [
        "button[aria-label='Close']", "[data-testid='modal-close']",
        "button:has-text('Not Now')", "button:has-text('Maybe Later')",
        "button:has-text('Skip')", "[class*='closeButton']", "[class*='CloseButton']",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click(timeout=2000)
                await asyncio.sleep(0.3)
        except Exception:
            pass


async def _fill(page: Page, selector: str, value: str) -> None:
    if not value or str(value).startswith("YOUR_"):
        return
    try:
        inp = page.locator(selector).first
        if await inp.is_visible(timeout=1500):
            await inp.fill(value, timeout=3000)
            await asyncio.sleep(0.3)
    except Exception:
        pass
