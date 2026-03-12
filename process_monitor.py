#!/usr/bin/env python3
"""
watchdog.py - Gold Tier Process Monitor
========================================
Monitors all PM2 processes every 5 minutes.
Logs status to /Logs/watchdog.log.
Creates a Needs_Action file if any process is down for > 2 consecutive checks.
"""

import os
import sys
import json
import time
import logging
import subprocess
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
except ImportError:
    pass

VAULT_DIR    = Path(__file__).parent
LOGS_DIR     = VAULT_DIR / "Logs"
NEEDS_ACTION = VAULT_DIR / "Needs_Action"

load_dotenv(VAULT_DIR / ".env")

CHECK_INTERVAL = int(os.getenv("WATCHDOG_INTERVAL", "300"))   # 5 minutes
ALERT_AFTER    = int(os.getenv("WATCHDOG_ALERT_AFTER", "2"))  # alert after N consecutive failures

WATCHED = ["file-watcher", "gmail", "ralph", "whatsapp", "linkedin"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(VAULT_DIR / "watchdog.log"),
    ],
)
logger = logging.getLogger("watchdog")


def _audit(action: str, detail: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    today    = datetime.now().strftime("%Y-%m-%d")
    json_log = LOGS_DIR / f"{today}.json"
    entry    = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "actor": "watchdog", "action": action, "detail": detail}
    records  = []
    if json_log.exists():
        try:
            records = json.loads(json_log.read_text(encoding="utf-8"))
        except Exception:
            pass
    records.append(entry)
    json_log.write_text(json.dumps(records, indent=2), encoding="utf-8")


def get_pm2_status() -> dict:
    """Return {name: status} for all PM2 processes."""
    try:
        result = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True, text=True, timeout=15
        )
        processes = json.loads(result.stdout)
        return {p["name"]: p["pm2_env"]["status"] for p in processes}
    except Exception as e:
        logger.error(f"Could not read PM2 status: {e}")
        return {}


def restart_process(name: str) -> bool:
    try:
        subprocess.run(["pm2", "restart", name], capture_output=True, timeout=30)
        logger.info(f"Restarted: {name}")
        _audit("restart", f"auto-restarted {name}")
        return True
    except Exception as e:
        logger.error(f"Failed to restart {name}: {e}")
        return False


def create_alert(name: str, consecutive: int) -> None:
    NEEDS_ACTION.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    epoch    = int(time.time())
    filename = f"action_watchdog_alert_{name}_{epoch}.md"
    content  = f"""---
type: "watchdog_alert"
process: "{name}"
consecutive_failures: "{consecutive}"
received_at: "{ts}"
status: "pending"
---

# Process Down Alert: {name}

**Process:** {name}
**Down for:** {consecutive} consecutive checks ({consecutive * CHECK_INTERVAL // 60} min)
**Detected at:** {ts}

The watchdog attempted auto-restart. If the process is still offline, manual intervention is needed.

Check logs with: `pm2 logs {name} --err --lines 30`
"""
    (NEEDS_ACTION / filename).write_text(content, encoding="utf-8")
    logger.warning(f"Alert created: {filename}")
    _audit("alert_created", f"{name} down for {consecutive} checks")


def main():
    logger.info("=" * 55)
    logger.info("Watchdog — Starting")
    logger.info(f"  Watching:  {', '.join(WATCHED)}")
    logger.info(f"  Interval:  {CHECK_INTERVAL}s")
    logger.info(f"  Alert after: {ALERT_AFTER} failures")
    logger.info("=" * 55)

    failure_counts: dict = {name: 0 for name in WATCHED}

    while True:
        statuses = get_pm2_status()
        ts       = datetime.now().strftime("%H:%M:%S")

        all_ok = True
        for name in WATCHED:
            status = statuses.get(name, "unknown")
            if status == "online":
                if failure_counts[name] > 0:
                    logger.info(f"[{ts}] {name}: recovered (back online)")
                    _audit("recovered", f"{name} back online")
                failure_counts[name] = 0
            elif status == "stopped":
                # Intentionally stopped by the user — do NOT restart, not a failure
                failure_counts[name] = 0
                logger.info(f"[{ts}] {name}: stopped (intentional — skipping)")
            else:
                # errored, unknown, etc. — unexpected crash, restart it
                all_ok = False
                failure_counts[name] += 1
                count = failure_counts[name]
                logger.warning(f"[{ts}] {name}: {status} (failure #{count})")
                # Try to restart
                restart_process(name)
                # Alert after threshold
                if count >= ALERT_AFTER:
                    create_alert(name, count)
                    failure_counts[name] = 0  # reset to avoid alert spam

        if all_ok:
            logger.info(f"[{ts}] All processes online")

        _audit("health_check", json.dumps({n: statuses.get(n, "unknown") for n in WATCHED}))
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
