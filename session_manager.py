"""
session_manager.py
──────────────────
Handles persistent Playwright browser context so the bot stays logged-in
across restarts.  On first run you capture the session manually; every
subsequent run the saved cookies / localStorage are reused.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from playwright.async_api import (
    BrowserContext,
    Playwright,
    async_playwright,
)
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SESSION_FILE = Path(os.getenv("SESSION_FILE", "session/blinkit_session.json"))
HEADED_MODE  = os.getenv("HEADED_MODE", "true").lower() == "true"
BLINKIT_URL  = "https://blinkit.com"

# Chrome args that help avoid headless-detection fingerprinting
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--window-size=1280,900",
    "--lang=en-IN",
    "--disable-extensions",
]


async def _apply_stealth(page) -> None:
    """Inject JS patches before the page sees any scripts."""
    await page.add_init_script("""
        // Mask webdriver flag
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        // Spoof plugins length
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        // Spoof languages
        Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en'] });
        // Chrome runtime stub
        window.chrome = { runtime: {} };
    """)


class SessionManager:
    """
    Usage
    -----
    async with SessionManager() as sm:
        context = await sm.get_context()
        page    = await context.new_page()
        ...
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    # ── context manager ──────────────────────────────────────────────────────

    async def __aenter__(self) -> "SessionManager":
        self._playwright = await async_playwright().start()
        return self

    async def __aexit__(self, *_) -> None:
        if self._context:
            await self._save_session(self._context)
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()

    # ── public API ───────────────────────────────────────────────────────────

    async def get_context(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        self._context = await self._build_context()
        return self._context

    async def capture_session_interactively(self) -> None:
        """
        Opens a visible browser window.
        Log in to Blinkit manually, then press <Enter> in the terminal.
        The session is saved to SESSION_FILE for reuse.
        """
        logger.info("🔑  Starting interactive session capture …")
        context = await self._build_context(force_headed=True, load_saved=False)
        page = await context.new_page()
        await _apply_stealth(page)
        await page.goto(BLINKIT_URL, wait_until="domcontentloaded")

        print("\n" + "═" * 60)
        print("  Browser opened.  Please:")
        print("  1. Log in to Blinkit (OTP / Google).")
        print("  2. Set your delivery location.")
        print("  3. Press <Enter> here when done.")
        print("═" * 60 + "\n")
        input()

        await self._save_session(context)
        await context.close()
        logger.info("✅  Session saved to %s", SESSION_FILE)

    # ── internals ────────────────────────────────────────────────────────────

    async def _build_context(
        self,
        force_headed: bool = False,
        load_saved: bool = True,
    ) -> BrowserContext:
        assert self._playwright is not None

        headless = not (HEADED_MODE or force_headed)
        browser = await self._playwright.chromium.launch(
            headless=headless,
            args=STEALTH_ARGS,
        )

        storage_state = None
        if load_saved and SESSION_FILE.exists():
            logger.info("📂  Loading saved session from %s", SESSION_FILE)
            storage_state = str(SESSION_FILE)
        else:
            logger.warning("⚠️  No saved session found — starting fresh.")

        context = await browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            geolocation={"latitude": 17.4485, "longitude": 78.3908},
            permissions=["geolocation"],
        )

        # Route to block heavy tracking/ad scripts (speed + stealth)
        await context.route(
            "**/{doubleclick,googletagmanager,analytics,clarity,hotjar,sentry}**",
            lambda route: route.abort(),
        )

        return context

    @staticmethod
    async def _save_session(context: BrowserContext) -> None:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        state = await context.storage_state()
        SESSION_FILE.write_text(json.dumps(state, indent=2))
        logger.info("💾  Session persisted to %s", SESSION_FILE)
