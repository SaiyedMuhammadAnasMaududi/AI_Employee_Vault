#!/usr/bin/env python3
"""
file_watcher.py - Bronze Tier File System Watcher
==================================================
Monitors a drop folder (default: ~/AI_Drops/) for new files.
When a file is detected, creates an .md action file in the
Obsidian vault's /Needs_Action/ folder with metadata.

Usage:
    pip install watchdog
    python file_watcher.py

Configuration:
    Edit DROP_FOLDER and VAULT_PATH below to match your setup.
"""

import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

try:
    from watchdog.observers.polling import PollingObserver as Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("Error: 'watchdog' library not found.")
    print("Install it with: pip install watchdog")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration - Edit these paths to match your environment
# ---------------------------------------------------------------------------

# Folder to monitor for new file drops
DROP_FOLDER = r"C:\Users\123\aidrops" if sys.platform == "win32" else "/mnt/c/Users/123/aidrops"

# Path to the Obsidian vault's Needs_Action folder
VAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Needs_Action")

# File extensions to watch (empty list = watch all files)
WATCHED_EXTENSIONS = [".txt", ".pdf", ".docx", ".xlsx", ".csv", ".png", ".jpg", ".eml"]

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "file_watcher.log")
        ),
    ],
)
logger = logging.getLogger("file_watcher")


# ---------------------------------------------------------------------------
# Watcher handler
# ---------------------------------------------------------------------------

class DropHandler(FileSystemEventHandler):
    """Handles new files appearing in the drop folder."""

    def on_created(self, event):
        """Triggered when a new file is created in the drop folder."""
        # Ignore directories
        if event.is_directory:
            return

        file_path = event.src_path
        file_name = os.path.basename(file_path)
        file_ext = os.path.splitext(file_name)[1].lower()

        # If we have a watch list, only process matching extensions
        if WATCHED_EXTENSIONS and file_ext not in WATCHED_EXTENSIONS:
            logger.info(f"Skipping '{file_name}' (extension '{file_ext}' not in watch list)")
            return

        logger.info(f"New file detected: {file_name}")

        # Wait briefly for the file to finish writing
        time.sleep(1)

        try:
            self._create_action_file(file_path, file_name, file_ext)
        except Exception as e:
            logger.error(f"Failed to create action file for '{file_name}': {e}")

    def _create_action_file(self, file_path, file_name, file_ext):
        """Create a .md action file in /Needs_Action/ with metadata."""
        # Gather file metadata
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            file_size = 0

        dropped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        safe_name = file_name.replace(" ", "_").replace(".", "_")
        action_file_name = f"action_{safe_name}_{int(time.time())}.md"
        action_file_path = os.path.join(VAULT_PATH, action_file_name)

        # Build the markdown content with YAML frontmatter
        content = f"""---
type: file_drop
original_name: "{file_name}"
size: {file_size}
dropped_at: "{dropped_at}"
status: pending
---

# New File Drop: {file_name}

## Details
- **Type:** file_drop
- **Original Name:** {file_name}
- **Extension:** {file_ext}
- **Size:** {file_size} bytes
- **Dropped At:** {dropped_at}
- **Source Path:** {file_path}

## Action Required
Review this file and take appropriate action. Move to /Done when complete.
"""

        # Write the action file
        with open(action_file_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Action file created: {action_file_path}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    """Start the file system watcher."""
    # Ensure the drop folder exists
    if not os.path.exists(DROP_FOLDER):
        logger.info(f"Creating drop folder: {DROP_FOLDER}")
        os.makedirs(DROP_FOLDER, exist_ok=True)

    # Ensure the Needs_Action folder exists
    if not os.path.exists(VAULT_PATH):
        logger.error(f"Vault Needs_Action folder not found: {VAULT_PATH}")
        logger.error("Please check VAULT_PATH configuration.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Bronze Tier File Watcher - Starting")
    logger.info(f"  Monitoring:  {DROP_FOLDER}")
    logger.info(f"  Actions to:  {VAULT_PATH}")
    logger.info(f"  Extensions:  {WATCHED_EXTENSIONS or 'ALL'}")
    logger.info("=" * 60)
    logger.info("Waiting for new files... (Ctrl+C to stop)")

    # Set up the observer
    event_handler = DropHandler()
    observer = Observer()
    observer.schedule(event_handler, DROP_FOLDER, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down watcher...")
        observer.stop()

    observer.join()
    logger.info("Watcher stopped.")


if __name__ == "__main__":
    main()
