"""
main.py
───────
Entry point for the Hot Wheels Blinkit bot.

Usage
─────
  # First run (capture login session):
  python main.py --capture-session

  # Normal monitoring loop:
  python main.py

  # Dry run (no cart / no Telegram):
  python main.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── logging setup (before any local imports) ──────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE  = os.getenv("LOG_FILE", "logs/bot.log")

Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level       = getattr(logging, LOG_LEVEL, logging.INFO),
    format      = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt     = "%Y-%m-%d %H:%M:%S",
    handlers    = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)

# ── local imports ─────────────────────────────────────────────────────────────

from session_manager import SessionManager
from blinkit_scraper import BlinkitScraper
from filter          import filter_products
from buyer           import BlinkitBuyer
from notifier        import (
    alert_cycle_start,
    alert_stock_found,
    alert_error,
    alert_info,
    Product,
)

# ── config ────────────────────────────────────────────────────────────────────

from config import POLL_INTERVAL_MIN as POLL_MIN, POLL_INTERVAL_MAX as POLL_MAX

# ── argument parsing ──────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Hot Wheels Blinkit Bot")
    p.add_argument(
        "--capture-session",
        action="store_true",
        help="Open browser for manual login then save session",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Run scraper + filter only; skip cart and Telegram",
    )
    p.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Stop after N cycles (0 = run forever)",
    )
    return p.parse_args()


# ── core pipeline ─────────────────────────────────────────────────────────────

async def run_cycle(
    sm: SessionManager,
    cycle: int,
    dry_run: bool,
) -> None:
    """Single poll cycle: scrape → filter → buy → notify."""

    if not dry_run:
        await alert_cycle_start(cycle)

    context = await sm.get_context()

    # ── 1. Scrape ─────────────────────────────────────────────────────────────
    try:
        async with BlinkitScraper(context) as scraper:
            raw_products = await scraper.search()
    except Exception as exc:
        logger.error("Scraper error: %s", exc)
        if not dry_run:
            await alert_error("Scraper", exc)
        return

    logger.info("Cycle %d: %d raw products found", cycle, len(raw_products))

    # ── 2. Filter ─────────────────────────────────────────────────────────────
    candidates = filter_products(raw_products)

    if not candidates:
        logger.info("Cycle %d: no matching products after filter", cycle)
        return

    logger.info("Cycle %d: %d candidate(s) passed filter", cycle, len(candidates))

    # ── 3. Alert & Buy ────────────────────────────────────────────────────────
    buyer = BlinkitBuyer(context)

    for product in candidates:
        pobj = Product(
            name       = product["name"],
            price      = product["price"],
            product_id = product.get("product_id", ""),
            url        = product["url"],
        )

        if not dry_run:
            await alert_stock_found(pobj)
            await buyer.buy(product)
        else:
            logger.info(
                "[DRY RUN] Would buy: %s ₹%.0f  in_stock=%s",
                product["name"],
                product["price"],
                product["in_stock"],
            )


# ── main loop ─────────────────────────────────────────────────────────────────

async def main() -> None:
    args = _parse_args()

    async with SessionManager() as sm:

        # ── session capture mode ──────────────────────────────────────────────
        if args.capture_session:
            await sm.capture_session_interactively()
            logger.info("Session capture complete. Run without --capture-session to start monitoring.")
            return

        # ── startup notification ──────────────────────────────────────────────
        mode_tag = " [DRY RUN]" if args.dry_run else ""
        logger.info("🚀  Hot Wheels bot starting%s …", mode_tag)
        if not args.dry_run:
            await alert_info(f"🚀 Hot Wheels bot started{mode_tag}")

        # ── polling loop ──────────────────────────────────────────────────────
        cycle = 0
        while True:
            cycle += 1
            logger.info("─" * 50)
            logger.info("Starting cycle #%d", cycle)

            try:
                await run_cycle(sm, cycle, args.dry_run)
            except Exception as exc:
                logger.error("Unhandled error in cycle %d: %s", cycle, exc)
                if not args.dry_run:
                    await alert_error(f"cycle #{cycle}", exc)

            # ── stop after N cycles if requested ──────────────────────────────
            if args.cycles and cycle >= args.cycles:
                logger.info("Reached requested cycle limit (%d). Exiting.", args.cycles)
                break

            # ── randomised sleep ──────────────────────────────────────────────
            delay = random.uniform(POLL_MIN, POLL_MAX)
            logger.info("💤  Sleeping %.1fs before next cycle …", delay)
            await asyncio.sleep(delay)


# ── entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
