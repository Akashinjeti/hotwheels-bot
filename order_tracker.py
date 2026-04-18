"""
order_tracker.py
────────────────
Persists how many units of each target product have been successfully ordered.
Survives bot restarts via a JSON file.

Used by filter.py to skip products that have hit their max_qty quota.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

TRACKER_FILE = Path("session/order_tracker.json")
_lock        = Lock()


def _load() -> dict[str, int]:
    if TRACKER_FILE.exists():
        try:
            return json.loads(TRACKER_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save(data: dict[str, int]) -> None:
    TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACKER_FILE.write_text(json.dumps(data, indent=2))


def get_ordered_qty(product_id: str) -> int:
    """Return how many units of product_id have been ordered so far."""
    with _lock:
        return _load().get(product_id, 0)


def record_order(product_id: str, qty: int = 1) -> int:
    """Increment the order count for product_id. Returns new total."""
    with _lock:
        data = _load()
        data[product_id] = data.get(product_id, 0) + qty
        _save(data)
        logger.info("📝  order_tracker: %s → %d ordered", product_id, data[product_id])
        return data[product_id]


def quota_remaining(product_id: str, max_qty: int) -> int:
    """
    Return how many more units can still be ordered.
    max_qty == 0 means unlimited → returns a large number.
    """
    if max_qty == 0:
        return 9999
    ordered = get_ordered_qty(product_id)
    return max(0, max_qty - ordered)


def reset(product_id: str | None = None) -> None:
    """Reset tracker. Pass None to reset all products."""
    with _lock:
        if product_id is None:
            _save({})
            logger.info("order_tracker: full reset")
        else:
            data = _load()
            data.pop(product_id, None)
            _save(data)
            logger.info("order_tracker: reset %s", product_id)


def summary() -> dict[str, int]:
    """Return full {product_id: qty_ordered} dict."""
    with _lock:
        return _load()
