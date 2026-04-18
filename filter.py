"""
filter.py  (v2 — exact product whitelist + quota enforcement)
─────────────────────────────────────────────────────────────
Only products that appear in config.TARGET_PRODUCTS pass.
Quota (max_qty) is enforced via order_tracker.py across restarts.

Each passing product dict is enriched with:
  • "_target"    : the matching TARGET_PRODUCTS entry
  • "_quota_left": how many more units we're allowed to order
"""

from __future__ import annotations

import logging
from typing import Any

from config        import TARGET_PRODUCTS, MAX_PRICE_INR
from order_tracker import quota_remaining

logger = logging.getLogger(__name__)


def filter_products(
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Return products that:
      1. Are in stock
      2. Match a TARGET_PRODUCTS entry (all keywords present in name)
      3. Have remaining quota  (max_qty 0 = unlimited)
      4. Are within the price cap
    """
    passed: list[dict[str, Any]] = []

    for p in products:
        name     = str(p.get("name", "")).strip()
        price    = float(p.get("price", 0))
        in_stock = bool(p.get("in_stock", False))

        # ① must be in stock
        if not in_stock:
            logger.debug("✗ out-of-stock  %s", name[:50])
            continue

        # ② price cap
        if MAX_PRICE_INR and price > MAX_PRICE_INR:
            logger.debug("✗ price ₹%.0f > cap  %s", price, name[:40])
            continue

        # ③ must match a target product
        target = _match_target(name)
        if target is None:
            logger.debug("✗ not in whitelist  %s", name[:50])
            continue

        # ④ quota check
        remaining = quota_remaining(target["id"], target["max_qty"])
        if remaining <= 0:
            logger.info(
                "✗ quota exhausted (%s, max=%d)  skipping",
                target["id"], target["max_qty"]
            )
            continue

        logger.info(
            "✅ PASS  %-50s  ₹%.0f  quota_left=%s",
            name[:50], price,
            "∞" if target["max_qty"] == 0 else remaining,
        )
        enriched = dict(p)
        enriched["_target"]     = target
        enriched["_quota_left"] = remaining
        passed.append(enriched)

    logger.info("Filter: %d/%d products passed", len(passed), len(products))
    return passed


def _match_target(name: str) -> dict | None:
    """
    Return the first TARGET_PRODUCTS entry whose keywords all appear
    (case-insensitive) in the product name.
    """
    name_lower = name.lower()
    for target in TARGET_PRODUCTS:
        if all(kw.lower() in name_lower for kw in target["keywords"]):
            return target
    return None
