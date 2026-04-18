"""
config.py
─────────
Central configuration for the Hot Wheels Blinkit bot.

Replace the PLACEHOLDER values with your real details before running.
"""

# ── Your delivery profile ─────────────────────────────────────────────────────

USER_PROFILE = {
    "name":    "Akash Injeti",            # e.g. "Rahul Sharma"
    "phone":   "7893587879",        # e.g. "9876543210"
    "address": {
        "line1":   "REGAL VISTAS CO-LIVING",    # e.g. "Flat 4B, Regal Vistas Co Living"
        "line2":   "MEGA HILLS",             # e.g. "Hitech City Road, Madhapur"
        "city":    "AYYAPA SOCIETY,Madhapur",
        "state":   "Telangana",
        "pincode": "500081",          # e.g. "500081"
    },
    # GPS for Blinkit location lock — get from maps.google.com
    "lat": 17.4485,
    "lng": 78.3908,
}

# ── Target product catalogue ──────────────────────────────────────────────────
#
# Rules:
#   max_qty : int  → maximum units to ever order (across all bot restarts)
#               0  → unlimited (order every time it's in stock)
#
# Matching is fuzzy substring (all keywords must appear in product name,
# case-insensitive).  Keep keywords specific enough to avoid false positives.

TARGET_PRODUCTS = [
    {
        "id":       "ferrari_f1",
        "name":     "Hot Wheels Formula 1 Scuderia Ferrari HP Die Cast Car",
        "keywords": ["formula 1", "scuderia ferrari", "hp"],
        "max_qty":  0,   # ← unlimited — buy every stock hit
    },
    {
        "id":       "ferrari_dino",
        "name":     "Hot Wheels Ferrari Dino 206GT Die Cast Car",
        "keywords": ["ferrari", "dino", "206"],
        "max_qty":  0,   # ← unlimited
    },
    {
        "id":       "aston_martin",
        "name":     "Hot Wheels 2024 Aston Martin Vantage GT3 Die Cast Car",
        "keywords": ["aston martin", "vantage", "gt3"],
        "max_qty":  1,   # ← one-time only
    },
    {
        "id":       "honda_civic",
        "name":     "Hot Wheels 2018 Honda Civic Type R Die Cast Car",
        "keywords": ["honda civic", "type r"],
        "max_qty":  1,
    },
    {
        "id":       "toyota_supra",
        "name":     "Hot Wheels Toyota GR Supra Die Cast Car",
        "keywords": ["toyota", "gr supra"],
        "max_qty":  1,
    },
    {
        "id":       "porsche_911",
        "name":     "Hot Wheels Porsche 911 Carrera Die Cast Car",
        "keywords": ["porsche", "911", "carrera"],
        "max_qty":  1,
    },
    {
        "id":       "mario_kart",
        "name":     "Hot Wheels Standard Mario Kart Die Cast Car",
        "keywords": ["mario kart"],
        "max_qty":  1,
    },
]

# ── Price guard ───────────────────────────────────────────────────────────────

MAX_PRICE_INR = 250   # never buy if price exceeds this (0 = no cap)

# ── Payment ───────────────────────────────────────────────────────────────────

PAYMENT_METHOD = "COD"   # "COD" | "UPI" | "CARD"
AUTO_PLACE_ORDER = True  # True = fully automatic; False = pause before final confirm

# ── Poll timing ───────────────────────────────────────────────────────────────

POLL_INTERVAL_MIN = 20   # seconds
POLL_INTERVAL_MAX = 40

# ── Retry / cooldown ──────────────────────────────────────────────────────────

MAX_RETRIES   = 3
CART_COOLDOWN = 300    # seconds before the same product_id can be re-added
