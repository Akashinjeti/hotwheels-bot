"""
notifier.py
───────────
Sends Telegram alerts at every important stage of the pipeline.
Falls back to console logging if Telegram credentials are missing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

TG_API  = f"https://api.telegram.org/bot{TOKEN}"

EMOJI = {
    "stock":    "🟢",
    "cart":     "🛒",
    "checkout": "✅",
    "error":    "🔴",
    "warn":     "⚠️",
    "info":     "ℹ️",
    "search":   "🔍",
    "sleep":    "💤",
}


class AlertType(Enum):
    STOCK_FOUND    = auto()
    ADDED_TO_CART  = auto()
    CHECKOUT_DONE  = auto()
    ERROR          = auto()
    WARNING        = auto()
    INFO           = auto()


@dataclass
class Product:
    name:       str
    price:      float
    product_id: str
    url:        str
    in_stock:   bool = True


# ── internal helpers ─────────────────────────────────────────────────────────

async def _send(text: str) -> None:
    """Fire-and-forget Telegram message (HTML parse mode)."""
    if not TOKEN or not CHAT_ID:
        logger.warning("Telegram not configured — skipping alert:\n%s", text)
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{TG_API}/sendMessage",
                json={
                    "chat_id":    CHAT_ID,
                    "text":       text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
    except Exception as exc:                        # noqa: BLE001
        logger.error("Telegram send failed: %s", exc)


def _fmt_price(price: float) -> str:
    return f"₹{price:.0f}"


# ── public API ───────────────────────────────────────────────────────────────

async def alert_stock_found(product: Product) -> None:
    msg = (
        f"{EMOJI['stock']} <b>Hot Wheels in Stock!</b>\n\n"
        f"🏎  <b>{product.name}</b>\n"
        f"💰  {_fmt_price(product.price)}\n"
        f"🔗  <a href='{product.url}'>View on Blinkit</a>\n"
        f"🆔  <code>{product.product_id}</code>"
    )
    logger.info("ALERT stock_found: %s", product.name)
    await _send(msg)


async def alert_added_to_cart(product: Product) -> None:
    msg = (
        f"{EMOJI['cart']} <b>Added to Cart</b>\n\n"
        f"🏎  <b>{product.name}</b>\n"
        f"💰  {_fmt_price(product.price)}\n"
        f"Proceeding to checkout …"
    )
    logger.info("ALERT added_to_cart: %s", product.name)
    await _send(msg)


async def alert_checkout_reached(product: Product) -> None:
    msg = (
        f"{EMOJI['checkout']} <b>Checkout Reached — Human action needed!</b>\n\n"
        f"🏎  <b>{product.name}</b>\n"
        f"💰  {_fmt_price(product.price)}\n"
        f"⏳  Waiting for OTP / payment …"
    )
    logger.info("ALERT checkout_reached: %s", product.name)
    await _send(msg)


async def alert_error(context: str, error: Exception | str) -> None:
    msg = (
        f"{EMOJI['error']} <b>Bot Error</b>\n\n"
        f"<b>Context:</b> {context}\n"
        f"<b>Error:</b> <code>{error}</code>"
    )
    logger.error("ALERT error [%s]: %s", context, error)
    await _send(msg)


async def alert_warning(text: str) -> None:
    msg = f"{EMOJI['warn']} <b>Warning</b>\n{text}"
    logger.warning("ALERT warning: %s", text)
    await _send(msg)


async def alert_info(text: str) -> None:
    msg = f"{EMOJI['info']} {text}"
    logger.info("ALERT info: %s", text)
    await _send(msg)


async def alert_cycle_start(cycle: int) -> None:
    msg = f"{EMOJI['search']} <b>Cycle #{cycle}</b> — scanning Blinkit for Hot Wheels …"
    logger.info("Cycle #%d started", cycle)
    await _send(msg)
