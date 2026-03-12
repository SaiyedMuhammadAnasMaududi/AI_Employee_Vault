#!/usr/bin/env python3
"""
whatsapp_watcher.py - Silver Tier WhatsApp Watcher
====================================================
Uses Playwright to open WhatsApp Web, scan for unread messages containing
trigger keywords, and create .md action files in /Needs_Action/.

Dependencies:
    pip install playwright python-dotenv
    python -m playwright install chromium

First run — must do auth setup first:
    python3 auth_setup.py --whatsapp
    → Browser opens, scan the QR code with your phone.
    → Session saved to WHATSAPP_SESSION_PATH.

Subsequent runs (headless, no browser window needed):
    python3 whatsapp_watcher.py
    Session is reused automatically.

WSL note:
    Requires display for first-time QR scan (handled by auth_setup.py).
    After session is saved, runs headless — no display needed.
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from base_watcher import BaseWatcher, write_action_file  # noqa: E402

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Error: 'playwright' not found.")
    print("Install with: pip install playwright && python -m playwright install chromium")
    sys.exit(1)

# ---------------------------------------------------------------------------
# WhatsApp Web selectors (as of early 2026 — may need updating)
# ---------------------------------------------------------------------------
WA_URL            = "https://web.whatsapp.com"
UNREAD_BADGE_SEL  = "span[data-testid='icon-unread-count']"
CHAT_TITLE_SEL    = "span[data-testid='conversation-info-header-chat-title']"
MSG_SEL           = "div.message-in span.selectable-text"
QR_SEL            = "canvas[aria-label='Scan me!']"
MSG_INPUT_SEL     = "div[contenteditable='true'][data-tab='10']"
SEND_BTN_SEL      = "button[data-testid='send']"


class WhatsAppWatcher(BaseWatcher):
    """Polls WhatsApp Web for unread keyword-matching messages."""

    def __init__(self):
        poll_interval = int(os.getenv("WHATSAPP_POLL_INTERVAL", "60"))
        super().__init__(name="whatsapp_watcher", poll_interval=poll_interval)

        self.session_path = Path(
            os.getenv("WHATSAPP_SESSION_PATH", "whatsapp_session")
        )
        keywords_raw = os.getenv("WHATSAPP_KEYWORDS", "urgent,invoice,approve,payment,asap,important")
        self.keywords = [kw.strip().lower() for kw in keywords_raw.split(",") if kw.strip()]

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._seen: set[str] = set()  # "sender|message_preview" dedup keys

    # ------------------------------------------------------------------
    # BaseWatcher interface
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Launch Chromium with persistent session and load WhatsApp Web.
        If session is missing or expired, sleep and retry — never crash-loops PM2.
        """
        while True:
            # ── Check session directory ──────────────────────────────────
            if not self.session_path.exists() or not any(self.session_path.iterdir()):
                self.logger.error(
                    "WhatsApp session not found. "
                    "Run:  python3 auth_setup.py --whatsapp"
                )
                self.logger.info("Sleeping 5 min, then rechecking...")
                time.sleep(300)
                continue

            self.session_path.mkdir(parents=True, exist_ok=True)

            # ── Try to launch and load ───────────────────────────────────
            try:
                self._playwright = sync_playwright().start()
                # Stealth mode: hide automation flags so WhatsApp Web
                # doesn't detect headless Chromium and block the session.
                self._context = self._playwright.chromium.launch_persistent_context(
                    str(self.session_path),
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                    ignore_default_args=["--enable-automation"],
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/121.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 720},
                )
                # Remove navigator.webdriver flag that WhatsApp detects
                self._context.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
                )
                self._page = self._context.new_page()
                self._page.goto(WA_URL, timeout=60_000, wait_until="domcontentloaded")
                self._wait_for_load()
                self.logger.info(
                    "WhatsApp Web ready. Auto-replying to all real person messages."
                )
                return  # success

            except Exception as e:
                self.logger.error(f"WhatsApp session invalid or expired: {e}")
                self.logger.error(
                    "Re-run auth:  python3 auth_setup.py --whatsapp"
                )
                # Clean up browser resources before sleeping
                try:
                    if self._context:   self._context.close()
                    if self._playwright: self._playwright.stop()
                except Exception:
                    pass
                self._context   = None
                self._playwright = None
                self._page      = None
                self.logger.info("Sleeping 10 min before retrying...")
                time.sleep(600)

    def check(self) -> int:
        """Click the Unread filter tab, then reply to each visible chat item."""
        new_count = 0

        # ── Title check ────────────────────────────────────────────────────
        try:
            title = self._page.title()
            self.logger.info(f"Poll: title='{title}'")
            if not title.startswith('('):
                return 0
        except Exception as e:
            self.logger.warning(f"Title check failed: {e}")
            return 0

        # ── DOM diagnostic (first poll only) ──────────────────────────────
        if not hasattr(self, '_dom_dumped'):
            self._dom_dumped = True
            try:
                d = self._page.evaluate("""
                    () => ({
                        elCount: document.querySelectorAll('*').length,
                        bodyText: (document.body.innerText||'').slice(0,400),
                        ids: [...document.querySelectorAll('[id]')].map(e=>e.id).filter(Boolean).slice(0,20),
                        ariaLabels: [...document.querySelectorAll('[aria-label]')]
                            .map(e=>e.getAttribute('aria-label')).slice(0,20),
                        roles: [...document.querySelectorAll('[role]')]
                            .map(e=>e.getAttribute('role')).slice(0,20),
                        buttons: [...document.querySelectorAll('button')]
                            .map(e=>(e.innerText||e.getAttribute('aria-label')||'').slice(0,30)).slice(0,10)
                    })
                """)
                self.logger.info(f"DOM: elCount={d['elCount']} bodyLen={len(d['bodyText'])}")
                self.logger.info(f"  ids={d['ids']}")
                self.logger.info(f"  aria={d['ariaLabels'][:10]}")
                self.logger.info(f"  roles={list(set(d['roles']))[:10]}")
                self.logger.info(f"  buttons={d['buttons']}")
                self.logger.info(f"  bodyText={d['bodyText']!r}")
            except Exception as de:
                self.logger.info(f"DOM dump failed: {de}")

        # ── Click "Unread" filter tab ──────────────────────────────────────
        # WhatsApp Web has tabs: All | Unread | Favourites | Groups
        try:
            clicked_tab = self._page.evaluate("""
                () => {
                    // Find any button/element whose visible text or aria-label
                    // is exactly "Unread" (or contains it as a whole word)
                    const all = [...document.querySelectorAll('button, [role="tab"], [role="button"], span, div')];
                    for (const el of all) {
                        const txt = (el.innerText || '').trim();
                        const aria = el.getAttribute('aria-label') || '';
                        if ((txt === 'Unread' || aria === 'Filter by Unread') && el.offsetWidth > 0) {
                            el.click();
                            return txt || aria;
                        }
                    }
                    return null;
                }
            """)
            if clicked_tab:
                self.logger.info(f"  Clicked Unread filter: {clicked_tab!r}")
                time.sleep(2)
            else:
                self.logger.info("  Unread filter tab not found — proceeding anyway")
        except Exception as e:
            self.logger.info(f"  Filter click failed: {e}")

        # ── Get all visible chat list items ───────────────────────────────
        try:
            chat_rows = self._page.evaluate("""
                () => {
                    // Chat rows: visible divs/li in the left panel,
                    // roughly 55-120px tall and 200-500px wide
                    const rows = [];
                    for (const el of document.querySelectorAll('[role="listitem"], [role="row"], li')) {
                        const h = el.offsetHeight, w = el.offsetWidth;
                        if (h >= 55 && h <= 120 && w >= 200 && w <= 600) {
                            const box = el.getBoundingClientRect();
                            rows.push({
                                aria:  el.getAttribute('aria-label') || '',
                                title: el.getAttribute('title') || '',
                                text:  (el.innerText || '').slice(0, 200),
                                cx: box.left + box.width/2,
                                cy: box.top  + box.height/2,
                                h, w
                            });
                        }
                    }
                    // Also try divs if no listitem/row found
                    if (rows.length === 0) {
                        for (const el of document.querySelectorAll('#pane-side div, [data-testid="cell-frame-container"]')) {
                            const h = el.offsetHeight, w = el.offsetWidth;
                            if (h >= 55 && h <= 120 && w >= 200 && w <= 600) {
                                const box = el.getBoundingClientRect();
                                rows.push({
                                    aria:  el.getAttribute('aria-label') || '',
                                    title: el.getAttribute('title') || '',
                                    text:  (el.innerText || '').slice(0, 200),
                                    cx: box.left + box.width/2,
                                    cy: box.top  + box.height/2,
                                    h, w
                                });
                            }
                        }
                    }
                    return rows;
                }
            """)
            self.logger.info(f"  {len(chat_rows)} chat row(s) found")
            for r in chat_rows[:3]:
                self.logger.info(f"    row h={r['h']} aria={r['aria']!r} text={r['text'][:60]!r}")
        except Exception as e:
            self.logger.warning(f"Chat row query failed: {e}")
            return 0

        if not chat_rows:
            # Fallback: try pressing Ctrl+Alt+T to jump to next unread
            self.logger.info("  No rows found — trying Ctrl+Alt+T shortcut")
            try:
                self._page.keyboard.press("Control+Alt+T")
                time.sleep(2)
                main_msgs = self._get_visible_messages()
                if main_msgs:
                    sender = self._get_chat_title()
                    dedup = f"kbd|{sender}"
                    if dedup not in self._seen:
                        msg = main_msgs[-1]
                        reply = self._get_qwen_reply(sender, msg)
                        if reply and self._send_reply(reply):
                            self.logger.info(f"  Kbd replied to {sender} ✓")
                            new_count += 1
                            self._seen.add(dedup)
            except Exception as e:
                self.logger.error(f"  Kbd shortcut failed: {e}")
            return new_count

        # ── Process each chat row ─────────────────────────────────────────
        for row in chat_rows:
            try:
                sender  = self._extract_sender('', {'aria': row.get('aria',''),
                                                     'title': row.get('title',''),
                                                     'innerText': row.get('text','')})
                preview = row.get('text', '') or row.get('aria', '')
                dedup   = f"{sender}|{preview[:40]}"
                if dedup in self._seen:
                    self.logger.info(f"  Already seen: {sender}")
                    continue

                # Click via page.mouse at the row's centre
                cx, cy = row['cx'], row['cy']
                self._page.mouse.move(cx, cy)
                time.sleep(0.1)
                self._page.mouse.click(cx, cy)
                self.logger.info(f"  Clicked {sender!r} at ({cx:.0f},{cy:.0f})")
                time.sleep(4)

                # Best-effort read from #main
                main_msgs = self._get_visible_messages()
                if main_msgs:
                    message_for_qwen = main_msgs[-1]
                    self.logger.info(f"  {len(main_msgs)} lines from #main")
                else:
                    message_for_qwen = preview or f"[Message from {sender}]"
                    self.logger.info(f"  #main empty — using preview")

                reply = self._get_qwen_reply(sender, message_for_qwen)
                if reply:
                    sent = self._send_reply(reply)
                    if sent:
                        self.logger.info(f"  Auto-replied to {sender} ✓")
                        new_count += 1
                    else:
                        self.logger.warning(f"  Could not send to {sender} (read-only group or no input)")
                else:
                    self.logger.warning(f"  Qwen gave no reply for {sender}")

                self._seen.add(dedup)

            except Exception as e:
                self.logger.error(f"  Row error: {e}")

        return new_count

    def cleanup(self) -> None:
        """Close browser and Playwright."""
        if self._context:
            self._context.close()
        if self._playwright:
            self._playwright.stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _wait_for_load(self) -> None:
        """Wait for WhatsApp Web to be ready (QR scan or session restore)."""
        self.logger.info("Waiting for WhatsApp Web to load...")

        # Selectors that indicate WhatsApp is fully loaded (try in order)
        LOADED_SELECTORS = [
            "div[data-testid='chat-list']",
            "#pane-side",
            "div[aria-label='Chat list']",
            "div[role='grid']",
        ]

        try:
            # If QR appears → session expired, user must re-run auth setup
            qr = self._page.wait_for_selector(QR_SEL, timeout=8_000)
            if qr:
                self.logger.error(
                    "QR code detected — session expired. "
                    "Run: python3 auth_setup.py --whatsapp"
                )
                raise PlaywrightTimeout("QR code shown — session not valid")
        except PlaywrightTimeout as e:
            if "QR code shown" in str(e):
                raise
            # No QR in 8s → good, session is restoring

        # Try each selector with 90s total timeout
        loaded = False
        for sel in LOADED_SELECTORS:
            try:
                self._page.wait_for_selector(sel, timeout=90_000)
                self.logger.info(f"WhatsApp Web ready (matched: {sel})")
                loaded = True
                break
            except PlaywrightTimeout:
                continue

        if not loaded:
            raise PlaywrightTimeout(
                "WhatsApp chat list not found after 90s — "
                "bot detection or session issue"
            )

    def _get_main_text(self) -> str:
        """Get the full innerText of #main (chat panel) — no selector needed."""
        try:
            return self._page.evaluate(
                "() => { const m = document.querySelector('#main'); return m ? m.innerText : ''; }"
            ) or ""
        except Exception:
            return ""

    def _get_chat_title(self) -> str:
        """Parse sender name from first meaningful line of #main innerText."""
        text = self._get_main_text()
        for line in text.splitlines():
            line = line.strip()
            if line and len(line) >= 2 and len(line) <= 80 and not line.isdigit():
                return line
        return "unknown"

    def _get_visible_messages(self) -> list[str]:
        """Extract message lines from #main innerText (lines 3+ chars, not timestamps)."""
        import re as _re
        text = self._get_main_text()
        messages = []
        for line in text.splitlines():
            line = line.strip()
            if (len(line) >= 3
                    and not _re.match(r'^\d{1,2}:\d{2}', line)   # skip timestamps
                    and not _re.match(r'^\d{1,2}/\d{1,2}', line)  # skip dates
                    and line not in ('online', 'typing...', 'recording...')):
                messages.append(line)
        return messages

    def _extract_sender(self, badge_aria: str, row_info: dict) -> str:
        """Extract sender name from badge aria-label or chat row attributes."""
        import re as _re
        # Try row aria-label: e.g. "Chat with John, last message: Hello"
        row_aria = row_info.get('aria', '')
        if row_aria:
            m = _re.match(r'(?:Chat with\s+)?([^,\n]+)', row_aria)
            if m:
                return m.group(1).strip()
        # Try title attribute
        title = row_info.get('title', '').strip()
        if title and len(title) <= 80:
            return title
        # Try first meaningful line of innerText
        text = row_info.get('innerText', '')
        for line in text.splitlines():
            line = line.strip()
            if line and 2 <= len(line) <= 80 and not line.isdigit():
                return line
        return 'unknown'

    def _get_qwen_reply(self, sender: str, message: str) -> str:
        """Call Qwen CLI to draft a WhatsApp reply. Returns reply text or empty string."""
        import subprocess
        prompt = (
            f"You are an AI assistant replying to a WhatsApp message on behalf of your employer.\n"
            f"Sender: {sender}\n"
            f"Message: {message}\n\n"
            f"Write a short, friendly, professional reply in 1-3 sentences.\n"
            f"Sign off as: AI Assistant\n"
            f"Output ONLY the reply text. No extra commentary."
        )
        try:
            result = subprocess.run(
                ["qwen", prompt, "--output-format", "text", "--approval-mode", "yolo"],
                capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=60,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception as e:
            self.logger.error(f"Qwen error: {e}")
            return ""

    def _send_reply(self, reply_text: str) -> bool:
        """Type and send a reply. Waits for input, tries multiple selectors."""
        try:
            # Wait up to 6s for any contenteditable to appear in #main
            try:
                self._page.wait_for_selector(
                    "#main [contenteditable='true']", timeout=6000
                )
            except Exception:
                pass  # Will fall through to JS search

            result = self._page.evaluate("""
                () => {
                    const main = document.querySelector('#main');
                    if (!main) return {ok: false, reason: 'no #main'};

                    // Search ANYWHERE in #main (not just footer)
                    const selectors = [
                        '[data-tab="10"][contenteditable="true"]',
                        '[aria-label="Type a message"]',
                        '[aria-placeholder="Type a message"]',
                        '[title="Type a message"]',
                        '[contenteditable="true"][role="textbox"]',
                        'footer [contenteditable="true"]',
                        '[contenteditable="true"]',
                    ];
                    for (const sel of selectors) {
                        const el = main.querySelector(sel);
                        if (el && el.offsetWidth > 0 && el.offsetHeight > 0) {
                            el.focus();
                            return {ok: true, sel};
                        }
                    }
                    // Debug info
                    const allCE = [...main.querySelectorAll('[contenteditable]')]
                        .map(e => e.getAttribute('contenteditable') + ' ' + e.tagName);
                    return {ok: false, reason: 'no input', allCE, mainHTML: main.innerHTML.slice(1500, 1800)};
                }
            """)
            if not result.get('ok'):
                ce = result.get('allCE', [])
                mhtml = result.get('mainHTML', '')
                self.logger.warning(f"No input — contenteditable els: {ce} | html: {mhtml[:100]!r}")
                return False

            self.logger.info(f"  Input via {result.get('sel','?')!r}")
            time.sleep(0.3)
            self._page.keyboard.type(reply_text, delay=20)
            time.sleep(0.3)
            self._page.keyboard.press("Enter")
            time.sleep(1)
            return True
        except Exception as e:
            self.logger.error(f"Send reply error: {e}")
            return False

    def _create_action_file(self, sender: str, message: str) -> Path:
        """Write a .md action file for a keyword-matched WhatsApp message."""
        received_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        matched_kws = [kw for kw in self.keywords if kw in message.lower()]
        safe_sender = sender[:40].replace(" ", "_")

        frontmatter = {
            "type": "whatsapp_message",
            "from": sender,
            "received_at": received_at,
            "keywords_matched": ", ".join(matched_kws),
            "sensitive": "true" if any(k in matched_kws for k in ["invoice", "payment"]) else "false",
            "status": "pending",
        }

        body = f"""# WhatsApp Message: {sender}

## Details
- **From:** {sender}
- **Received At:** {received_at}
- **Keywords Matched:** {', '.join(matched_kws)}
- **Sensitive:** {'YES — route to /Pending_Approval/' if frontmatter['sensitive'] == 'true' else 'No'}

## Message
{message[:1000]}

## Action Required
Review this message and take appropriate action. Move to /Done when complete.
"""

        return write_action_file(f"whatsapp_{safe_sender}", frontmatter, body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    WhatsAppWatcher().run()
