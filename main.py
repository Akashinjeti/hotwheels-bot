"""
main.py  (v3 — with session upload server)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE  = os.getenv("LOG_FILE", "logs/bot.log")
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level    = getattr(logging, LOG_LEVEL, logging.INFO),
    format   = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt  = "%Y-%m-%d %H:%M:%S",
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

from session_manager import SessionManager
from blinkit_scraper import BlinkitScraper
from filter          import filter_products
from buyer           import BlinkitBuyer
from notifier        import (
    alert_cycle_start, alert_stock_found,
    alert_error, alert_info, Product,
)
from session_upload  import start_upload_server
from config          import POLL_INTERVAL_MIN as POLL_MIN, POLL_INTERVAL_MAX as POLL_MAX


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Hot Wheels Blinkit Bot")
    p.add_argument("--capture-session", action="store_true")
    p.add_argument("--dry-run",         action="store_true")
    p.add_argument("--cycles",          type=int, default=0)
    p.add_argument("--no-upload-server",action="store_true",
                   help="Disable the session upload web server")
    return p.parse_args()


async def run_cycle(sm: SessionManager, cycle: int, dry_run: bool) -> None:
    if not dry_run:
        await alert_cycle_start(cycle)

    context = await sm.get_context()

    try:
        async with BlinkitScraper(context) as scraper:
            raw_products = await scraper.search()
    except Exception as exc:
        logger.error("Scraper error: %s", exc)
        if not dry_run:
            await alert_error("Scraper", exc)
        return

    logger.info("Cycle %d: %d raw products", cycle, len(raw_products))
    candidates = filter_products(raw_products)

    if not candidates:
        logger.info("Cycle %d: no matching products", cycle)
        return

    buyer = BlinkitBuyer(context)
    for product in candidates:
        pobj = Product(
            name=product["name"], price=product["price"],
            product_id=product.get("product_id", ""), url=product["url"],
        )
        if not dry_run:
            await alert_stock_found(pobj)
            await buyer.buy(product)
        else:
            logger.info("[DRY RUN] Would buy: %s ₹%.0f", product["name"], product["price"])


async def main() -> None:
    args = _parse_args()

    # Start session upload server (so you can paste cookies via browser)
    if not args.capture_session and not args.no_upload_server:
        start_upload_server()

    async with SessionManager() as sm:
        if args.capture_session:
            await sm.capture_session_interactively()
            return

        mode = " [DRY RUN]" if args.dry_run else ""
        logger.info("🚀  Hot Wheels bot starting%s …", mode)
        if not args.dry_run:
            await alert_info(f"🚀 Hot Wheels bot started{mode}")

        cycle = 0
        while True:
            cycle += 1
            logger.info("─" * 50)
            logger.info("Starting cycle #%d", cycle)

            try:
                await run_cycle(sm, cycle, args.dry_run)
            except Exception as exc:
                logger.error("Unhandled error cycle %d: %s", cycle, exc)
                if not args.dry_run:
                    await alert_error(f"cycle #{cycle}", exc)

            if args.cycles and cycle >= args.cycles:
                break

            delay = random.uniform(POLL_MIN, POLL_MAX)
            logger.info("💤  Sleeping %.1fs …", delay)
            await asyncio.sleep(delay)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
