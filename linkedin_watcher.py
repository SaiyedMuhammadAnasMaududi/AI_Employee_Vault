#!/usr/bin/env python3
"""
linkedin_watcher.py - Silver Tier LinkedIn Watcher + Poster
============================================================
Three modes:

  1. Default (watcher mode):
     Watches /Approved/ for action_type=linkedin_post files.
     When found: posts to LinkedIn via Playwright, moves to /Done/.

     python3 linkedin_watcher.py

  2. Post mode (called by ralph_wrapper or manually):
     Posts a single piece of content directly.

     python3 linkedin_watcher.py --post --content "My post text here"

  3. Monitor mode:
     Watches LinkedIn notifications for keyword mentions.
     Creates Needs_Action files for flagged items.

     python3 linkedin_watcher.py --monitor

First run — must run auth_setup.py first:
     python3 auth_setup.py --linkedin

Dependencies:
    pip install playwright python-dotenv watchdog
    python3 -m playwright install chromium
"""

import os
import sys
import re
import time
import shutil
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, date

try:
    from dotenv import load_dotenv
except ImportError:
    print("Error: python-dotenv not found. Run: pip install python-dotenv")
    sys.exit(1)

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("Error: playwright not found.")
    print("Run: pip install playwright && python3 -m playwright install chromium")
    sys.exit(1)

try:
    from watchdog.observers.polling import PollingObserver
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("Error: watchdog not found. Run: pip install watchdog")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths and config
# ---------------------------------------------------------------------------

VAULT_DIR       = Path(__file__).parent
APPROVED_DIR    = VAULT_DIR / "Approved"
DONE_DIR        = VAULT_DIR / "Done"
NEEDS_ACTION    = VAULT_DIR / "Needs_Action"
LOGS_DIR        = VAULT_DIR / "Logs"
AGENT_LOG       = LOGS_DIR / "agent_log.md"

load_dotenv(VAULT_DIR / ".env")

LI_SESSION_PATH  = Path(os.getenv("LINKEDIN_SESSION_PATH",
                         str(VAULT_DIR / "linkedin_session")))
POLL_INTERVAL    = int(os.getenv("LINKEDIN_POLL_INTERVAL", "60"))
LI_KEYWORDS_RAW  = os.getenv("LINKEDIN_KEYWORDS", "urgent,invoice,partnership,collaboration")
LI_KEYWORDS      = [k.strip().lower() for k in LI_KEYWORDS_RAW.split(",") if k.strip()]

# LinkedIn URLs
AUTO_POST_HOUR   = int(os.getenv("LINKEDIN_AUTO_POST_HOUR", "9"))   # 9 AM default
LAST_POST_FILE   = VAULT_DIR / "linkedin_last_post_date.txt"
RETRY_FILE       = VAULT_DIR / "linkedin_retry_time.txt"
POSTS_HISTORY    = LOGS_DIR / "linkedin_posts_history.md"
LI_CROSS_POST_FB = os.getenv("LINKEDIN_CROSS_POST_FB", "true").lower() == "true"

# One curated professional image per topic for Instagram cross-posts
TOPIC_IMAGE_URLS = {
    "AI & Automation":  "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=1080&q=80",
    "Productivity":     "https://images.unsplash.com/photo-1484480974693-6ca0a78fb36b?w=1080&q=80",
    "Entrepreneurship": "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=1080&q=80",
    "Tech & Innovation":"https://images.unsplash.com/photo-1518770660439-4636190af475?w=1080&q=80",
}
DEFAULT_IMAGE_URL = "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=1080&q=80"

TOPICS = [
    "AI & Automation",
    "Productivity",
    "Entrepreneurship",
    "Tech & Innovation",
]

# Fallback posts used when Qwen is unavailable — 2 per topic, rotated by week
FALLBACK_POSTS = {
    "AI & Automation": [
        "AI isn't replacing jobs — it's replacing inefficiency.\n\nEvery hour your team spends on repetitive tasks is an hour not spent on creative thinking, client relationships, or strategy.\n\nThe businesses winning in 2026 aren't the ones with the biggest teams. They're the ones that automate the routine so their people can focus on what actually matters.\n\nHere's where to start:\n→ Map your top 5 repetitive tasks\n→ Identify which ones follow a clear pattern\n→ Automate one this week — even a simple email template saves hours\n\nSmall automations compound. One hour saved per day = 250 hours per year.\n\nWhat's one task you'd automate first?\n\n#AIAutomation #BusinessEfficiency #FutureOfWork #Productivity #AI",
        "The AI employee that never sleeps, never calls in sick, and never misses a deadline — that's what automation gives you.\n\nWe're living through the biggest shift in business operations since the internet. Companies that build AI into their workflows now will have an insurmountable advantage in 3 years.\n\nWhat AI can do for your business today:\n✅ Handle email triage and responses\n✅ Generate social media content\n✅ Create and send invoices\n✅ Monitor and alert on key metrics\n✅ Schedule and coordinate tasks\n\nThe question isn't whether to adopt AI — it's how fast.\n\nAre you building your AI advantage?\n\n#ArtificialIntelligence #Automation #BusinessGrowth #Entrepreneurship #TechInnovation",
    ],
    "Productivity": [
        "Most productivity advice is wrong.\n\nPeople chase time management systems, morning routines, and app stacks — but the real productivity killer is decision fatigue.\n\nEvery small decision you make throughout the day drains mental energy. By afternoon, your best thinking is gone.\n\nFix it with three principles:\n1. Automate decisions that repeat (email responses, scheduling, reporting)\n2. Batch similar tasks into dedicated blocks\n3. Protect your first 2 hours — no meetings, no email\n\nThe most productive people I know don't work harder. They've engineered their environment so their energy is spent on high-value decisions only.\n\nWhat's one decision you could automate or eliminate this week?\n\n#Productivity #DeepWork #TimeManagement #BusinessOwner #Efficiency",
        "You don't need more time. You need fewer interruptions.\n\nResearch shows it takes 23 minutes to regain focus after an interruption. If you're interrupted 8 times a day, that's over 3 hours of lost deep work — every single day.\n\nHow to protect your focus:\n→ Turn off non-critical notifications before 12pm\n→ Set email to check only at 9am, 1pm, and 5pm\n→ Use a 'do not disturb' block for your highest-priority task\n→ Automate status updates so colleagues don't need to ask\n\nDeep work is your competitive edge. Guard it.\n\nWhat's your biggest focus killer at work?\n\n#Productivity #FocusTime #DeepWork #WorkSmarter #BusinessProductivity",
    ],
    "Entrepreneurship": [
        "The hardest thing about entrepreneurship isn't building the product. It's building the business around it.\n\nMost founders I talk to are brilliant at what they do — but struggle with:\n→ Getting consistent clients\n→ Managing operations without burning out\n→ Scaling without sacrificing quality\n→ Handling admin while staying focused on growth\n\nThe solution isn't hiring faster. It's building systems first.\n\nA business with strong systems can scale. A business that depends entirely on the founder cannot.\n\nBuild the system before you need it. Future you will thank you.\n\nWhat system would make the biggest difference in your business right now?\n\n#Entrepreneurship #BusinessSystems #Startup #Founder #BusinessGrowth",
        "Most businesses fail not because of bad ideas — but because of poor execution on the basics.\n\nCash flow. Client acquisition. Follow-up. Invoicing. Relationships.\n\nNone of these are glamorous. All of them are essential.\n\nThe entrepreneurs who last aren't necessarily the most creative. They're the most consistent. They show up every day, do the unglamorous work, and build momentum.\n\nThree non-negotiables for any business:\n1. Know your numbers every week (revenue, expenses, outstanding)\n2. Follow up with every lead — most sales happen after the 5th touchpoint\n3. Automate the repetitive so you can focus on the relationship\n\nConsistency beats inspiration every time.\n\nWhat's the one thing you do consistently that drives your business forward?\n\n#Entrepreneurship #BusinessTips #SmallBusiness #Founder #Hustle",
    ],
    "Tech & Innovation": [
        "Technology doesn't create the future. People who understand technology do.\n\nThe most valuable skill in the next decade isn't coding — it's knowing which problems are worth solving with technology and which aren't.\n\nEvery tool, platform, and AI model is just a means to an end. The end is always human: serving clients better, working more efficiently, communicating more clearly.\n\nTech leaders I admire ask:\n→ What problem does this actually solve?\n→ Who is it for and what does success look like?\n→ Is the complexity worth the benefit?\n\nThe best technology feels invisible. It just works, and people wonder how they ever lived without it.\n\nWhat piece of technology has made the biggest difference in how you work?\n\n#TechInnovation #DigitalTransformation #FutureOfWork #Technology #Business",
        "We're at an inflection point in technology — and most businesses don't realise how fast things are moving.\n\nA year ago, AI-generated content was a novelty. Today it's a workflow. A year from now, fully autonomous AI agents will be handling entire business functions.\n\nThe companies getting ahead are:\n✅ Experimenting now, not waiting for the perfect solution\n✅ Training their teams on AI tools as they emerge\n✅ Building data systems that AI can actually use\n✅ Automating one process at a time, then scaling\n\nYou don't need to be a tech company to benefit from tech. You need to be a business that takes technology seriously.\n\nWhat's one emerging technology you're watching closely right now?\n\n#Technology #Innovation #AIBusiness #DigitalStrategy #FutureReady",
    ],
}

LI_FEED_URL      = "https://www.linkedin.com/feed/"
LI_NOTIF_URL     = "https://www.linkedin.com/notifications/"
LI_LOGIN_URL     = "https://www.linkedin.com/login"

# Selectors (LinkedIn early 2026 — update if LinkedIn changes UI)
SELECTORS = {
    # Feed / post composer
    "start_post_btn":  "button.share-box-feed-entry__trigger",
    "post_editor":     "div.ql-editor[data-placeholder]",
    "post_editor_alt": "div[role='textbox']",
    "post_submit":     "button.share-actions__primary-action",
    # Login
    "email_field":     "input#username",
    "pass_field":      "input#password",
    "login_btn":       "button[type='submit']",
    # Notifications
    "notif_items":     "div.nt-card-list article",
    "notif_text":      "span.nt-card__headline--3-line",
    # Login detection
    "feed_indicator":  "div.share-box-feed-entry",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(VAULT_DIR / "linkedin_watcher.log"),
    ],
)
logger = logging.getLogger("linkedin_watcher")


def append_log(message: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(AGENT_LOG, "a", encoding="utf-8") as f:
        f.write(f"\n## {ts} — {message}\n")


def parse_frontmatter(content: str) -> dict:
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    result = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith("#"):
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


# ---------------------------------------------------------------------------
# Browser session manager
# ---------------------------------------------------------------------------

class LinkedInSession:
    """Manages a persistent Playwright browser context for LinkedIn."""

    def __init__(self):
        self._playwright = None
        self._context    = None
        self._page       = None

    def start(self) -> bool:
        """Start browser with saved cookies. Returns True if logged in."""
        import json
        cookies_path = LI_SESSION_PATH.parent / "linkedin_cookies.json"
        if not cookies_path.exists():
            logger.error(
                f"LinkedIn cookies not found at {cookies_path}\n"
                "Run auth setup first: python3 auth_setup.py --linkedin"
            )
            return False

        cookies = json.loads(cookies_path.read_text(encoding="utf-8"))

        self._playwright = sync_playwright().start()
        browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1280,800",
            ],
        )
        self._context = browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        self._context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        self._context.add_cookies(cookies)
        self._page = self._context.new_page()

        # Verify session — retry on DNS errors
        for dns_attempt in range(6):
            try:
                self._page.goto(LI_FEED_URL, timeout=30_000, wait_until="domcontentloaded")
                break
            except Exception as e:
                if "ERR_NAME_NOT_RESOLVED" in str(e) and dns_attempt < 5:
                    logger.warning(f"DNS not ready yet, retrying in 10s... ({dns_attempt+1}/6)")
                    time.sleep(10)
                    continue
                logger.error(f"LinkedIn session error: {e}")
                self.stop()
                return False

        time.sleep(3)
        current_url = self._page.url
        if "login" in current_url or "authwall" in current_url:
            logger.error(
                "LinkedIn session expired. "
                "Re-run: python3 auth_setup.py --linkedin"
            )
            self.stop()
            return False

        logger.info(f"LinkedIn session active. URL: {current_url}")
        return True

    def stop(self):
        try:
            if self._context:
                self._context.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass

    @property
    def page(self):
        return self._page


# ---------------------------------------------------------------------------
# Core posting logic
# ---------------------------------------------------------------------------

def post_to_linkedin(session: LinkedInSession, content: str) -> bool:
    """
    Post text content to LinkedIn feed.
    Returns True on success.
    """
    page = session.page
    logger.info(f"Posting to LinkedIn ({len(content)} chars)...")

    try:
        # Navigate to feed
        page.goto(LI_FEED_URL, timeout=30_000, wait_until="domcontentloaded")
        time.sleep(2)

        # Click "Start a post"
        try:
            page.click(SELECTORS["start_post_btn"], timeout=8_000)
            logger.info("Clicked 'Start a post'")
        except PWTimeout:
            # Fallback: click the text area directly
            page.click("button:has-text('Start a post')", timeout=8_000)

        time.sleep(2)

        # Type content into editor
        editor = None
        for sel in [SELECTORS["post_editor"], SELECTORS["post_editor_alt"]]:
            try:
                editor = page.wait_for_selector(sel, timeout=6_000)
                break
            except PWTimeout:
                continue

        if not editor:
            logger.error("Could not find post editor — LinkedIn UI may have changed.")
            return False

        editor.click()
        page.keyboard.type(content, delay=30)
        logger.info("Content typed into editor.")
        time.sleep(1)

        # Click Post button
        try:
            post_btn = page.wait_for_selector(SELECTORS["post_submit"], timeout=8_000)
            post_btn.click()
            logger.info("Clicked Post button.")
        except PWTimeout:
            # Fallback
            page.click("button:has-text('Post')", timeout=8_000)

        time.sleep(3)

        # Verify post appeared (feed reloads after posting)
        logger.info("Post submitted successfully.")
        append_log(f"linkedin_watcher: POST PUBLISHED — {content[:100]}...")
        return True

    except Exception as e:
        logger.error(f"Posting failed: {e}")
        append_log(f"linkedin_watcher ERROR: post failed — {e}")
        # Save screenshot for debugging
        try:
            page.screenshot(path=str(VAULT_DIR / "linkedin_error.png"))
            logger.info("Screenshot saved: linkedin_error.png")
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# Notification monitor
# ---------------------------------------------------------------------------

def check_notifications(session: LinkedInSession) -> int:
    """
    Scan LinkedIn notifications for keyword-matching items.
    Creates Needs_Action files for flagged notifications.
    Returns count of new action files created.
    """
    page = session.page
    NEEDS_ACTION.mkdir(parents=True, exist_ok=True)
    new_count = 0

    try:
        page.goto(LI_NOTIF_URL, timeout=30_000, wait_until="domcontentloaded")
        time.sleep(2)

        items = page.query_selector_all(SELECTORS["notif_items"])
        logger.info(f"Found {len(items)} notification items.")

        for item in items[:20]:  # check latest 20
            try:
                text_el = item.query_selector(SELECTORS["notif_text"])
                text = text_el.inner_text().strip() if text_el else ""
            except Exception:
                continue

            if not text:
                continue

            matched = [kw for kw in LI_KEYWORDS if kw in text.lower()]
            if not matched:
                continue

            ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fm  = {
                "type":             "linkedin_notification",
                "received_at":      ts,
                "keywords_matched": ", ".join(matched),
                "sensitive":        "false",
                "status":           "pending",
            }
            body = f"""# LinkedIn Notification

## Details
- **Received At:** {ts}
- **Keywords Matched:** {', '.join(matched)}

## Content
{text[:500]}

## Action Required
Review this LinkedIn notification and take appropriate action.
Move to /Done when complete.
"""
            epoch    = int(time.time())
            filename = f"action_linkedin_notif_{epoch}.md"
            outpath  = NEEDS_ACTION / filename

            # Skip if already captured (same text in recent files)
            recent = list(NEEDS_ACTION.glob("action_linkedin_notif_*.md"))
            already_seen = any(
                text[:80] in f.read_text(encoding="utf-8")
                for f in recent[-10:]
                if f.exists()
            )
            if already_seen:
                continue

            fm_lines = ["---"]
            for k, v in fm.items():
                fm_lines.append(f'{k}: "{v}"')
            fm_lines.append("---")

            outpath.write_text(
                "\n".join(fm_lines) + "\n\n" + body + "\n", encoding="utf-8"
            )
            logger.info(f"Notification action file created: {filename}")
            append_log(f"linkedin_watcher: notification → {filename}")
            new_count += 1

    except Exception as e:
        logger.error(f"Notification check error: {e}")

    return new_count


# ---------------------------------------------------------------------------
# Approved folder watcher (watcher mode)
# ---------------------------------------------------------------------------

class ApprovedLinkedInHandler(FileSystemEventHandler):
    """Detects linkedin_post files in /Approved/ and queues them for the main thread."""

    def __init__(self, post_queue):
        self.post_queue  = post_queue
        self._processing = set()

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".md" or str(path) in self._processing:
            return

        time.sleep(1)
        if not path.exists():
            return

        content = path.read_text(encoding="utf-8")
        fm      = parse_frontmatter(content)

        if fm.get("action_type", "").strip('"') != "linkedin_post":
            return  # not for us

        self._processing.add(str(path))
        logger.info(f"[Approved] LinkedIn post queued: {path.name}")

        post_content = fm.get("post_content", "").strip('"').replace("\\n", "\n")

        if not post_content:
            body_match = re.search(r"## Post Content\n(.*?)(\n##|$)", content, re.DOTALL)
            if body_match:
                post_content = body_match.group(1).strip()

        # Put (path, content) into queue — main thread will post it
        self.post_queue.put((path, post_content))
        self._processing.discard(str(path))


# ---------------------------------------------------------------------------
# Auto-post helpers
# ---------------------------------------------------------------------------

def get_fallback_post(topic: str) -> str:
    """Return a pre-written fallback post for the topic, rotated by ISO week number."""
    posts = FALLBACK_POSTS.get(topic, FALLBACK_POSTS["AI & Automation"])
    idx   = date.today().isocalendar()[1] % len(posts)  # rotate by week number
    logger.info(f"Using fallback post #{idx+1} for topic '{topic}'")
    return posts[idx]


def generate_linkedin_post(topic: str) -> str:
    """
    Generate a LinkedIn post via Qwen CLI.
    Falls back to pre-written posts if Qwen fails or is unavailable.
    """
    prompt = (
        f"Write a professional LinkedIn post about '{topic}' for an AI automation business. "
        "Requirements:\n"
        "- 150-250 words\n"
        "- Start with a bold, attention-grabbing opening line (1 sentence)\n"
        "- Include 3-5 actionable tips or insights as bullet points or numbered list\n"
        "- End with a thought-provoking question to encourage engagement\n"
        "- Close with 4-5 relevant hashtags on the last line\n"
        "- Tone: professional, confident, helpful — not salesy\n"
        "Output ONLY the post text — no preamble, no explanation, no markdown code blocks."
    )
    try:
        result = subprocess.run(
            ["qwen", prompt, "--output-format", "text", "--approval-mode", "yolo"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout.strip()
        if result.returncode != 0 or not output:
            logger.warning(f"Qwen failed (code {result.returncode}) — using fallback post.")
            return get_fallback_post(topic)
        # Validate length (LinkedIn max 3000 chars)
        if len(output) > 3000:
            output = output[:2990] + "..."
        logger.info(f"Qwen generated post: {len(output)} chars")
        return output
    except FileNotFoundError:
        logger.warning("Qwen CLI not found — using fallback post.")
        return get_fallback_post(topic)
    except subprocess.TimeoutExpired:
        logger.warning("Qwen timed out — using fallback post.")
        return get_fallback_post(topic)
    except Exception as e:
        logger.warning(f"generate_linkedin_post error: {e} — using fallback post.")
        return get_fallback_post(topic)


def get_todays_topic() -> str:
    """Return today's topic by cycling through TOPICS based on day ordinal."""
    return TOPICS[date.today().toordinal() % len(TOPICS)]


def should_auto_post() -> bool:
    """Return True if we haven't posted today and it's past AUTO_POST_HOUR."""
    if datetime.now().hour < AUTO_POST_HOUR:
        return False
    if LAST_POST_FILE.exists():
        last = LAST_POST_FILE.read_text(encoding="utf-8").strip()
        if last == date.today().isoformat():
            return False
    return True


def mark_posted_today() -> None:
    """Persist today's date so we don't double-post."""
    LAST_POST_FILE.write_text(date.today().isoformat(), encoding="utf-8")
    # Clear retry file on success
    if RETRY_FILE.exists():
        RETRY_FILE.unlink()


def should_retry() -> bool:
    """Return True if a previous auto-post failed and retry wait (15 min) has passed."""
    if not RETRY_FILE.exists():
        return False
    try:
        retry_after = float(RETRY_FILE.read_text(encoding="utf-8").strip())
        return time.time() >= retry_after
    except Exception:
        return False


def schedule_retry(minutes: int = 15) -> None:
    """Schedule a retry after `minutes` minutes."""
    RETRY_FILE.write_text(str(time.time() + minutes * 60), encoding="utf-8")


def save_post_history(topic: str, content: str, source: str) -> None:
    """Append posted content to linkedin_posts_history.md for audit trail."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(POSTS_HISTORY, "a", encoding="utf-8") as f:
        f.write(f"\n---\n")
        f.write(f"## {ts} | Topic: {topic} | Source: {source}\n\n")
        f.write(content + "\n")
    logger.info(f"Post saved to history: {POSTS_HISTORY.name}")


def cross_post_to_meta(content: str, topic: str) -> None:
    """
    Cross-post to Facebook AND Instagram after a LinkedIn auto-post succeeds.
    Uses topic-mapped images so Instagram always has a valid image URL.
    """
    if not LI_CROSS_POST_FB:
        return
    meta_script = VAULT_DIR / "meta_social_mcp.py"
    if not meta_script.exists():
        logger.warning("meta_social_mcp.py not found — skipping cross-post.")
        return

    image_url = TOPIC_IMAGE_URLS.get(topic, DEFAULT_IMAGE_URL)

    # --- Facebook ---
    try:
        r = subprocess.run(
            [sys.executable, str(meta_script), "--action", "post_facebook",
             "--message", content],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            logger.info("Cross-posted to Facebook ✓")
            append_log("linkedin_watcher: cross-posted to Facebook ✓")
        else:
            logger.warning(f"Facebook cross-post failed: {r.stderr.strip()[:200]}")
    except Exception as e:
        logger.warning(f"Facebook cross-post error: {e}")

    # --- Instagram (always has image via topic map) ---
    try:
        r = subprocess.run(
            [sys.executable, str(meta_script), "--action", "post_instagram",
             "--message", content, "--image-url", image_url],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            logger.info(f"Cross-posted to Instagram ✓ (image: {topic})")
            append_log("linkedin_watcher: cross-posted to Instagram ✓")
        else:
            logger.warning(f"Instagram cross-post failed: {r.stderr.strip()[:200]}")
    except Exception as e:
        logger.warning(f"Instagram cross-post error: {e}")


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------

def run_watcher_mode():
    """Watch /Approved/ for linkedin_post files + poll notifications."""
    import queue as _queue

    # Retry session start — sleep instead of crash-looping PM2
    session = LinkedInSession()
    while not session.start():
        logger.error(
            "LinkedIn session invalid or expired. "
            "Run:  python3 auth_setup.py --linkedin"
        )
        logger.info("Sleeping 10 min before retrying...")
        time.sleep(600)
        session = LinkedInSession()

    logger.info("="*55)
    logger.info("LinkedIn Watcher — Starting")
    logger.info(f"  Approved dir:  {APPROVED_DIR}")
    logger.info(f"  Poll interval: {POLL_INTERVAL}s")
    logger.info(f"  Keywords:      {LI_KEYWORDS}")
    logger.info("="*55)

    APPROVED_DIR.mkdir(parents=True, exist_ok=True)

    post_queue = _queue.Queue()
    handler    = ApprovedLinkedInHandler(post_queue)
    observer   = PollingObserver()
    observer.schedule(handler, str(APPROVED_DIR), recursive=False)
    observer.start()

    try:
        cycle = 0
        while True:
            # Process any queued posts in the main thread (Playwright thread-safety)
            while not post_queue.empty():
                path, post_content = post_queue.get()
                if post_content:
                    success = post_to_linkedin(session, post_content)
                    status  = "POSTED" if success else "FAILED"
                    logger.info(f"[Approved] {status}: {path.name}")
                else:
                    logger.error(f"[Approved] No post_content found in {path.name}")
                DONE_DIR.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(DONE_DIR / path.name))
                logger.info(f"[Approved] Moved → /Done/{path.name}")

            time.sleep(POLL_INTERVAL)
            cycle += 1
            # Check notifications every 5 cycles
            if cycle % 5 == 0:
                count = check_notifications(session)
                if count:
                    logger.info(f"Notifications: {count} new action file(s) created.")

            # Auto-post check (once per day at AUTO_POST_HOUR)
            if should_auto_post() or should_retry():
                topic   = get_todays_topic()
                logger.info(f"Auto-post: generating post for topic '{topic}'...")
                content = generate_linkedin_post(topic)
                source  = "qwen" if content and "fallback" not in content.lower() else "fallback"
                if content:
                    success = post_to_linkedin(session, content)
                    if success:
                        mark_posted_today()
                        save_post_history(topic, content, source)
                        logger.info(f"Auto-post published ({topic}) ✓")
                        cross_post_to_meta(content, topic)
                    else:
                        logger.error("Auto-post failed — scheduling retry in 15 min")
                        schedule_retry(15)
                else:
                    logger.error("Post generation returned empty — scheduling retry in 15 min")
                    schedule_retry(15)
    except KeyboardInterrupt:
        logger.info("Shutting down LinkedIn watcher...")
        observer.stop()

    observer.join()
    session.stop()
    logger.info("LinkedIn watcher stopped.")


def run_post_mode(content: str):
    """Post a single piece of content to LinkedIn and exit."""
    session = LinkedInSession()
    if not session.start():
        sys.exit(1)

    success = post_to_linkedin(session, content)
    session.stop()
    sys.exit(0 if success else 1)


def run_monitor_mode():
    """Check notifications once and exit (useful for cron/testing)."""
    session = LinkedInSession()
    if not session.start():
        sys.exit(1)

    count = check_notifications(session)
    logger.info(f"Monitor check: {count} new action file(s) created.")
    session.stop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Playwright Watcher")
    parser.add_argument("--post",    action="store_true", help="Post mode: post content and exit")
    parser.add_argument("--content", type=str, default="",  help="Content to post (use with --post)")
    parser.add_argument("--monitor", action="store_true", help="Check notifications once and exit")
    args = parser.parse_args()

    if args.post:
        if not args.content:
            print("Error: --content is required with --post", file=sys.stderr)
            sys.exit(1)
        run_post_mode(args.content)
    elif args.monitor:
        run_monitor_mode()
    else:
        run_watcher_mode()
