# 🏎 Hot Wheels Blinkit Auto-Order Bot  (v2)

Monitors Blinkit for 7 specific Hot Wheels models, auto-adds to cart,
selects **Cash on Delivery**, and places the order fully automatically.
Ferrari F1 + Dino 206GT → unlimited orders. Other 5 → 1 each, forever.

---

## File Map

```
hotwheels_bot/
├── main.py             ← async poll loop + CLI
├── config.py           ← YOUR DETAILS + product catalogue  ← EDIT THIS
├── blinkit_scraper.py  ← network interception + DOM fallback
├── filter.py           ← exact whitelist + quota check
├── buyer.py            ← cart → COD → place order
├── notifier.py         ← Telegram alerts
├── session_manager.py  ← persistent login session
├── order_tracker.py    ← persists how many of each car ordered
├── requirements.txt
├── .env.example
├── session/
│   ├── blinkit_session.json   (auto-created)
│   └── order_tracker.json     (auto-created)
└── logs/
    └── bot.log
```

---

## Step 1 — Fill in your details  ← DO THIS FIRST

Open **`config.py`** and replace the placeholders:

```python
USER_PROFILE = {
    "name":    "Rahul Sharma",           # Your name
    "phone":   "9876543210",             # Mobile number (no +91)
    "address": {
        "line1":   "Flat 4B, Regal Vistas",
        "line2":   "Hitech City, Madhapur",
        "city":    "Hyderabad",
        "state":   "Telangana",
        "pincode": "500081",
    },
    "lat": 17.4485,   # from Google Maps
    "lng": 78.3908,
}
```

---

## Step 2 — Install

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium  # Linux only
cp .env.example .env
# Edit .env → add your TELEGRAM_TOKEN and CHAT_ID
```

---

## Step 3 — Capture Blinkit session (one-time)

```bash
python main.py --capture-session
```

A Chrome window opens. Log in with OTP, set your delivery location to
**Madhapur / 500081**, then press **Enter** in the terminal.
Session saved to `session/blinkit_session.json`.

---

## Step 4 — Run

```bash
# Full auto (live orders + Telegram alerts):
python main.py

# Dry run — prints matches, no cart, no Telegram:
python main.py --dry-run

# Run 3 cycles then exit (good for testing):
python main.py --cycles 3
```

---

## Product Rules

| Car | Quota |
|-----|-------|
| Hot Wheels Formula 1 Scuderia Ferrari HP | ∞ unlimited |
| Hot Wheels Ferrari Dino 206GT | ∞ unlimited |
| Hot Wheels 2024 Aston Martin Vantage GT3 | 1 (lifetime) |
| Hot Wheels 2018 Honda Civic Type R | 1 (lifetime) |
| Hot Wheels Toyota GR Supra | 1 (lifetime) |
| Hot Wheels Porsche 911 Carrera | 1 (lifetime) |
| Hot Wheels Standard Mario Kart | 1 (lifetime) |

Quota is stored in `session/order_tracker.json` and survives restarts.
To reset a quota manually:

```python
from order_tracker import reset
reset("aston_martin")   # reset one car
reset()                  # reset all
```

---

## Order Flow (fully automatic)

```
Detect in-stock product
       │
  Add to Cart ──────────────────── retry x3
       │
  Open /checkout
       │
  Confirm saved address ─────────── fills phone/name if prompted
       │
  Select "Cash on Delivery" ─────── tries 10 selector variants
       │
  Click "Place Order" ───────────── verifies success screen
       │
  Record in order_tracker.json
       │
  Telegram: "🎉 Order placed!"
```

---

## Telegram Alerts

| Event | Message |
|-------|---------|
| Cycle start | 🔍 Scanning… |
| Stock found | 🟢 Name + price + link |
| Added to cart | 🛒 Name |
| COD checkout | ✅ About to place order |
| Order placed | 🎉 Confirmation |
| Error | 🔴 Context + error |

Get your CHAT_ID: message `@userinfobot` on Telegram.

---

## 24/7 systemd (Linux)

```ini
# /etc/systemd/system/hotwheels-bot.service
[Unit]
Description=Hot Wheels Blinkit Bot
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/path/to/hotwheels_bot
ExecStart=/path/to/venv/bin/python main.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hotwheels-bot
sudo journalctl -u hotwheels-bot -f
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| 0 products every cycle | Session expired → `python main.py --capture-session` |
| COD not selected | Blinkit UI changed → inspect DevTools, add new selector to `COD_SELECTORS` in buyer.py |
| Order placed but tracker not updated | Check logs for "record_order" line; tracker file in `session/order_tracker.json` |
| Bot detected | Set `HEADED_MODE=true` in .env, increase poll intervals |
| "YOUR_MOBILE_NUMBER" in logs | Open config.py and fill in USER_PROFILE |
