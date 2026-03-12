#!/usr/bin/env python3
"""
meta_social_mcp.py - Gold Tier Meta (FB + IG) Social MCP
=========================================================
Dry-run only until META_ACCESS_TOKEN is set in .env.

Commands:
  post_facebook     --message TEXT [--image-url URL]
  post_instagram    --message TEXT [--image-url URL]
  generate_summary  --period {week|month}

All actions logged to /Logs/meta_social_actions.md + /Logs/YYYY-MM-DD.json
"""

import os
import sys
import json
import time
import logging
import argparse
import functools
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
except ImportError:
    print("Error: python-dotenv not found. Run: pip install python-dotenv")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VAULT_DIR = Path(__file__).parent
LOGS_DIR  = VAULT_DIR / "Logs"
META_LOG  = LOGS_DIR / "meta_social_actions.md"

load_dotenv(VAULT_DIR / ".env")

META_ACCESS_TOKEN   = os.getenv("META_ACCESS_TOKEN", "")   # empty = dry-run
META_PAGE_ID        = os.getenv("META_PAGE_ID", "")
META_IG_ID          = os.getenv("META_IG_ID", "")
META_API_BASE       = "https://graph.facebook.com/v18.0"
# Default image used for Instagram when no --image-url is supplied
META_DEFAULT_IG_IMAGE = os.getenv(
    "META_DEFAULT_IG_IMAGE",
    "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=1080&q=80",
)

# Always dry-run if no token
DRY_RUN = (not META_ACCESS_TOKEN) or os.getenv("META_DRY_RUN", "true").lower() == "true"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(VAULT_DIR / "meta_social_mcp.log"),
    ],
)
logger = logging.getLogger("meta_social_mcp")

if DRY_RUN:
    logger.info("META_SOCIAL: running in DRY-RUN mode (no real API calls)")


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def with_retry(retries: int = 3, delay: float = 2.0):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, retries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < retries:
                        wait = delay * (2 ** (attempt - 1))
                        logger.warning(f"[retry {attempt}/{retries}] {fn.__name__} failed: {e} — retrying in {wait:.0f}s")
                        time.sleep(wait)
            raise last_exc
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------

def _audit_log(action: str, params: dict, result: str, detail: str = "") -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(META_LOG, "a", encoding="utf-8") as f:
        f.write(f"\n## {ts} — {action}\n")
        f.write(f"- **Mode:** {'DRY-RUN' if DRY_RUN else 'LIVE'}\n")
        f.write(f"- **Params:** {json.dumps(params)}\n")
        f.write(f"- **Result:** {result}\n")
        if detail:
            f.write(f"- **Detail:** {detail}\n")

    today    = datetime.now().strftime("%Y-%m-%d")
    json_log = LOGS_DIR / f"{today}.json"
    entry    = {"timestamp": ts, "actor": "meta_social_mcp", "action": action,
                "mode": "dry-run" if DRY_RUN else "live",
                "params": params, "result": result, "detail": detail}
    records  = []
    if json_log.exists():
        try:
            records = json.loads(json_log.read_text(encoding="utf-8"))
        except Exception:
            records = []
    records.append(entry)
    json_log.write_text(json.dumps(records, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Meta Graph API client
# ---------------------------------------------------------------------------

class MetaSocialMCP:

    @with_retry(retries=3, delay=2.0)
    def _api_post(self, endpoint: str, payload: dict) -> dict:
        """POST to Meta Graph API (only called when not in dry-run)."""
        url  = f"{META_API_BASE}/{endpoint}?access_token={META_ACCESS_TOKEN}"
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(url, data=data,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def post_facebook(self, message: str, image_url: str = "") -> dict:
        params = {"platform": "facebook", "message": message[:100] + "...",
                  "image_url": image_url}
        logger.info(f"post_facebook: {len(message)} chars")

        if DRY_RUN:
            result = {"status": "dry-run", "platform": "facebook",
                      "message_preview": message[:120],
                      "note": "Set META_ACCESS_TOKEN + META_PAGE_ID to go live"}
            _audit_log("post_facebook", params, "dry-run", message[:200])
            print(json.dumps(result))
            return result

        try:
            payload = {"message": message}
            if image_url:
                payload["link"] = image_url
            resp   = self._api_post(f"{META_PAGE_ID}/feed", payload)
            result = {"status": "success", "platform": "facebook", "post_id": resp.get("id")}
            _audit_log("post_facebook", params, "success", str(result))
            print(json.dumps(result))
            return result
        except Exception as e:
            _audit_log("post_facebook", params, "error", str(e))
            logger.error(f"post_facebook failed: {e}")
            result = {"status": "error", "error": str(e)}
            print(json.dumps(result))
            return result

    def post_instagram(self, message: str, image_url: str = "") -> dict:
        params = {"platform": "instagram", "message": message[:100] + "...",
                  "image_url": image_url}
        logger.info(f"post_instagram: {len(message)} chars")

        if DRY_RUN:
            result = {"status": "dry-run", "platform": "instagram",
                      "message_preview": message[:120],
                      "note": "Set META_ACCESS_TOKEN + META_IG_ID to go live"}
            _audit_log("post_instagram", params, "dry-run", message[:200])
            print(json.dumps(result))
            return result

        try:
            if not image_url:
                image_url = META_DEFAULT_IG_IMAGE
                logger.info(f"No image_url provided — using default image.")
            # Step 1: create media container
            container = self._api_post(f"{META_IG_ID}/media",
                                       {"image_url": image_url, "caption": message})
            # Step 2: publish
            resp   = self._api_post(f"{META_IG_ID}/media_publish",
                                    {"creation_id": container["id"]})
            result = {"status": "success", "platform": "instagram", "post_id": resp.get("id")}
            _audit_log("post_instagram", params, "success", str(result))
            print(json.dumps(result))
            return result
        except Exception as e:
            _audit_log("post_instagram", params, "error", str(e))
            logger.error(f"post_instagram failed: {e}")
            result = {"status": "error", "error": str(e)}
            print(json.dumps(result))
            return result

    def generate_summary(self, period: str = "week") -> dict:
        """Read recent meta_social_actions.md and summarise activity."""
        logger.info(f"generate_summary: period={period}")
        days     = 7 if period == "week" else 30
        cutoff   = datetime.now() - timedelta(days=days)
        entries  = []

        if META_LOG.exists():
            for line in META_LOG.read_text(encoding="utf-8").splitlines():
                if line.startswith("## "):
                    try:
                        ts_str = line[3:22]
                        ts     = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        if ts >= cutoff:
                            entries.append(line[3:])
                    except Exception:
                        pass

        result = {
            "status":  "success",
            "period":  period,
            "total":   len(entries),
            "dry_run": DRY_RUN,
            "entries": entries[-20:],  # latest 20
            "note":    f"Social posts logged for last {days} days",
        }
        _audit_log("generate_summary", {"period": period}, "success", f"{len(entries)} entries")
        print(json.dumps(result, indent=2))
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Meta Social MCP (dry-run until token set)")
    parser.add_argument("--action",    required=True,
                        choices=["post_facebook", "post_instagram", "generate_summary"])
    parser.add_argument("--message",   default="")
    parser.add_argument("--image-url", default="", dest="image_url")
    parser.add_argument("--period",    default="week", choices=["week", "month"])
    args = parser.parse_args()

    meta = MetaSocialMCP()

    if args.action == "post_facebook":
        if not args.message:
            print(json.dumps({"status": "error", "error": "--message required"}))
            sys.exit(1)
        meta.post_facebook(args.message, args.image_url)
    elif args.action == "post_instagram":
        if not args.message:
            print(json.dumps({"status": "error", "error": "--message required"}))
            sys.exit(1)
        meta.post_instagram(args.message, args.image_url)
    elif args.action == "generate_summary":
        meta.generate_summary(args.period)


if __name__ == "__main__":
    main()
