#!/usr/bin/env python3
"""
auth_setup.py - One-time Auth Setup for Gmail, WhatsApp & LinkedIn
===================================================================

WhatsApp : Opens Linux Chromium. Scan the QR with your phone.
LinkedIn : Opens Linux Chromium. Log in with email + password.
           (Google login won't work here — set a LinkedIn password first.)
Gmail    : Opens browser for OAuth consent. Token saved automatically.

Usage:
    python3 auth_setup.py              # all three
    python3 auth_setup.py --gmail      # Gmail only
    python3 auth_setup.py --whatsapp   # WhatsApp only
    python3 auth_setup.py --linkedin   # LinkedIn only
"""

import os
import sys
import time
import argparse
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("Error: playwright not found. Run:  bash install.sh")
    sys.exit(1)

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False

VAULT_DIR       = Path(__file__).parent
WA_SESSION_PATH = Path(os.getenv("WHATSAPP_SESSION_PATH",
                        str(VAULT_DIR / "whatsapp_session")))
LI_SESSION_PATH = Path(os.getenv("LINKEDIN_SESSION_PATH",
                        str(VAULT_DIR / "linkedin_session")))


# ─── Gmail ───────────────────────────────────────────────────────────────────

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def setup_gmail():
    if not _GOOGLE_AVAILABLE:
        print("Error: Google libraries not installed. Run: bash install.sh")
        return

    creds_path = Path(os.getenv(
        "GMAIL_CREDENTIALS_PATH",
        str(VAULT_DIR.parent / ".secrets" / "secret.json")
    ))
    token_path = Path(os.getenv(
        "GMAIL_TOKEN_PATH",
        str(VAULT_DIR / "gmail_token.json")
    ))

    print()
    print("=" * 60)
    print("  GMAIL AUTH SETUP")
    print("=" * 60)

    if not creds_path.exists():
        print()
        print(f"  Credentials file not found: {creds_path}")
        print()
        print("  To get it:")
        print("  1. Go to console.cloud.google.com")
        print("  2. Select/create a project")
        print("  3. APIs & Services → Enable → Gmail API")
        print("  4. Credentials → Create → OAuth 2.0 Client → Desktop App")
        print("  5. Download JSON → save it to:")
        print(f"     {creds_path}")
        print()
        print("  Then re-run:  python3 auth_setup.py --gmail")
        return

    # Check if token already valid
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
            if creds.valid:
                print(f"\n  Gmail already authenticated (token: {token_path})")
                print("  Setup complete.\n")
                return
            if creds.expired and creds.refresh_token:
                print("\n  Refreshing expired Gmail token...")
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
                print("  Token refreshed. Setup complete.\n")
                return
        except Exception:
            pass

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), GMAIL_SCOPES)

    print()
    print("  Opening Gmail OAuth consent...")
    print()

    try:
        # Try automatic browser open first (works on some WSL setups)
        creds = flow.run_local_server(port=8080, open_browser=True)
    except Exception:
        # WSL fallback: print URL for manual open in Windows browser
        flow2 = InstalledAppFlow.from_client_secrets_file(str(creds_path), GMAIL_SCOPES)
        auth_url, _ = flow2.authorization_url(prompt="consent")
        print("  Could not open browser automatically.")
        print()
        print("  Open this URL in your Windows browser:")
        print()
        print(f"  {auth_url}")
        print()
        print("  After granting access, you'll be redirected to localhost:8080.")
        print("  (Keep this terminal open — it will catch the response automatically.)")
        print()
        creds = flow2.run_local_server(port=8080, open_browser=False)

    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"\n  Gmail token saved to: {token_path}")
    print("  Gmail setup complete.\n")


# ─── WhatsApp ────────────────────────────────────────────────────────────────

def setup_whatsapp():
    print()
    print("=" * 60)
    print("  WHATSAPP AUTH SETUP")
    print("=" * 60)
    print()
    print("  1. A browser window will open showing WhatsApp Web.")
    print("  2. Scan the QR code in the browser with your phone:")
    print("     WhatsApp → ⋮ (3 dots) → Linked Devices → Link a Device")
    print("  3. Your chats appear → session saved automatically.")
    print()
    input("Press ENTER to open the browser...")

    WA_SESSION_PATH.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        print("\n[WhatsApp] Opening browser...")
        ctx  = p.chromium.launch_persistent_context(
            str(WA_SESSION_PATH), headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
        page.goto("https://web.whatsapp.com", timeout=30_000,
                  wait_until="domcontentloaded")

        try:
            page.wait_for_selector("div[data-testid='chat-list']", timeout=6_000)
            print("\n[WhatsApp] ✓ Already logged in — session is still valid!")
            ctx.close()
            print("[WhatsApp] Setup complete.\n")
            return
        except PWTimeout:
            pass

        for sel in ["canvas[aria-label='Scan me!']", "div[data-ref]"]:
            try:
                page.wait_for_selector(sel, timeout=10_000)
                print("\n[WhatsApp] ✓ QR code visible — scan it now!")
                break
            except PWTimeout:
                continue
        else:
            print("\n[WhatsApp] Browser open — scan the QR code shown there.")

        print("[WhatsApp] Waiting up to 3 minutes for you to scan...")
        try:
            page.wait_for_selector("div[data-testid='chat-list']", timeout=180_000)
            print("\n[WhatsApp] ✓ Logged in! Session saved.")
            time.sleep(2)
        except PWTimeout:
            print("\n[WhatsApp] ✗ Timed out. Run again: python3 auth_setup.py --whatsapp")

        ctx.close()
    print("[WhatsApp] Browser closed. Setup complete.\n")


# ─── LinkedIn ────────────────────────────────────────────────────────────────

def setup_linkedin():
    print()
    print("=" * 60)
    print("  LINKEDIN AUTH SETUP")
    print("=" * 60)
    print()
    print("  IMPORTANT: Google login does NOT work in this browser.")
    print("  You must log in with LinkedIn email + password.")
    print()
    print("  Don't have a LinkedIn password? Set one first (2 min):")
    print("  → Open LinkedIn in your Windows browser")
    print("  → Click Me → Settings & Privacy → Sign in & Security")
    print("  → Set a password, then come back here.")
    print()
    input("Press ENTER to open the browser...")

    LI_SESSION_PATH.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(LI_SESSION_PATH),
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
            ignore_default_args=["--enable-automation"],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()
        page.goto("https://www.linkedin.com/login", timeout=30_000,
                  wait_until="domcontentloaded")

        print("\n[LinkedIn] Browser is open.")
        print("  → Log in with your email + password.")
        print("  → Wait until your LinkedIn feed (home page) is fully loaded.")
        print()

        # Loop until user is actually on the feed
        while True:
            input("Press ENTER once your LinkedIn feed is fully loaded...")
            time.sleep(2)
            # Check all open pages in context (LinkedIn may open feed in a new tab)
            all_urls = [p.url for p in ctx.pages]
            feed_url = next(
                (u for u in all_urls if any(x in u for x in ["feed", "/in/", "mynetwork", "jobs"])),
                None
            )
            if feed_url:
                print(f"\n[LinkedIn] ✓ Logged in!")
                break
            else:
                print(f"\n[LinkedIn] ✗ Not on the feed yet.")
                print(f"  Open pages: {all_urls}")
                print("  Please complete the login and make sure your feed is loaded.")
                print()

        # Save cookies to JSON so headless watcher can load them
        import json
        cookies = ctx.cookies(["https://www.linkedin.com"])
        cookies_path = LI_SESSION_PATH.parent / "linkedin_cookies.json"
        cookies_path.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        print(f"[LinkedIn] Cookies saved: {len(cookies)} cookies → {cookies_path}")
        ctx.close()

    print("[LinkedIn] Setup complete.\n")


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="One-time auth setup for Gmail, WhatsApp and LinkedIn"
    )
    parser.add_argument("--gmail",    action="store_true")
    parser.add_argument("--whatsapp", action="store_true")
    parser.add_argument("--linkedin",  action="store_true")
    args   = parser.parse_args()
    do_all = not args.gmail and not args.whatsapp and not args.linkedin

    if args.gmail or do_all:
        setup_gmail()
    if args.whatsapp or do_all:
        setup_whatsapp()
    if args.linkedin or do_all:
        setup_linkedin()

    print()
    print("=" * 60)
    print("  ALL AUTH SETUP COMPLETE")
    print("=" * 60)
    print()
    print("Start all watchers:  bash run_watchers.sh")
    print()


if __name__ == "__main__":
    main()
