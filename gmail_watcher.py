#!/usr/bin/env python3
"""
gmail_watcher.py - Silver Tier Gmail Watcher (IMAP)
=====================================================
Polls Gmail via IMAP for unread emails and creates .md action files
in /Needs_Action/ with YAML frontmatter.

Setup:
    1. Enable 2-Step Verification on your Google account
    2. Go to myaccount.google.com/apppasswords
    3. Create an App Password named "AI Employee"
    4. Add to .env:
         GMAIL_ADDRESS=you@gmail.com
         GMAIL_APP_PASSWORD=yourapppassword

No OAuth, no browser popup, no token expiry.
"""

import os
import sys
import imaplib
import email as email_lib
from email.header import decode_header
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from base_watcher import BaseWatcher, write_action_file  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass


class GmailWatcher(BaseWatcher):
    """Polls Gmail via IMAP, writes action .md files for unread emails."""

    # File that persists the last processed IMAP UID across restarts
    _UID_FILE = Path(__file__).parent / "gmail_last_uid.txt"

    def __init__(self):
        poll_interval = int(os.getenv("GMAIL_POLL_INTERVAL", "120"))
        super().__init__(name="gmail_watcher", poll_interval=poll_interval)

        self.address      = os.getenv("GMAIL_ADDRESS", "")
        self.app_password = os.getenv("GMAIL_APP_PASSWORD", "")

    def _load_last_uid(self) -> int:
        """Return the last UID we processed (0 = never run before)."""
        try:
            return int(self._UID_FILE.read_text().strip())
        except Exception:
            return 0

    def _save_last_uid(self, uid: int) -> None:
        """Persist the highest processed UID to disk."""
        try:
            self._UID_FILE.write_text(str(uid))
        except Exception as e:
            self.logger.warning(f"Could not save last UID: {e}")

    # ------------------------------------------------------------------
    # BaseWatcher interface
    # ------------------------------------------------------------------

    def setup(self) -> None:
        import time as _time

        while not self.address or not self.app_password:
            self.logger.error(
                "Gmail credentials not set. Add to .env:\n"
                "  GMAIL_ADDRESS=you@gmail.com\n"
                "  GMAIL_APP_PASSWORD=your16charpassword"
            )
            self.logger.info("Sleeping 5 min, then rechecking .env...")
            _time.sleep(300)
            self.address      = os.getenv("GMAIL_ADDRESS", "")
            self.app_password = os.getenv("GMAIL_APP_PASSWORD", "")

        # Test the connection — retry on DNS errors (WSL2 DNS can be slow to start)
        import time as _time
        for attempt in range(12):  # retry up to 12x with 10s gaps = 2 minutes
            try:
                mail = self._connect()
                mail.logout()
                self.logger.info(f"Gmail IMAP connected: {self.address}")
                return
            except Exception as e:
                if "Name or service not known" in str(e) or "Temporary failure" in str(e):
                    self.logger.warning(f"DNS not ready, retrying in 10s... ({attempt+1}/12)")
                    _time.sleep(10)
                    continue
                self.logger.error(f"Gmail connection failed: {e}")
                self.logger.error("Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env")
                self.logger.info("Sleeping 5 min before retrying...")
                _time.sleep(300)
                return  # exit setup, base_watcher will re-call it

    # Automated sender patterns to ignore
    IGNORE_PATTERNS = [
        "noreply", "no-reply", "donotreply", "do-not-reply",
        "notifications@", "notification@", "alerts@", "alert@",
        "newsletter", "mailer", "bounce", "postmaster",
        "linkedin.com", "jobs-listings", "jobalerts", "jobs-noreply",
        "info@linkedin", "mail.linkedin", "e.linkedin",
        "google.com", "googlemail", "accounts-noreply",
        "subscriptions@", "updates@", "digest@",
        "automated", "auto-confirm", "automailer",
        # Job boards
        "bayt.com", "notify@", "jobalert", "job-alert",
        "indeed.com", "glassdoor.com", "rozee.pk",
        # Common newsletter/promo senders
        "info@", "hello@", "team@", "support@",
        "marketing@", "promo@", "deals@", "offer@",
    ]

    SENSITIVE_KEYWORDS = ["invoice", "payment", "legal", "contract", "urgent",
                          "asap", "approve", "approval", "overdue", "due date",
                          "action required", "important notice"]

    def _is_automated(self, sender: str) -> bool:
        sender_lower = sender.lower()
        return any(pat in sender_lower for pat in self.IGNORE_PATTERNS)

    def _is_worth_acting_on(self, sender: str, subject: str, body: str) -> bool:
        """Return True for any email from a real person (not automated)."""
        # Skip automated/newsletter senders only
        if self._is_automated(sender):
            return False
        return True

    def _is_already_queued(self, uid: str) -> bool:
        """Return True if an action file for this UID already exists in Needs_Action."""
        needs_action = Path(__file__).parent / "Needs_Action"
        if not needs_action.exists():
            return False
        for f in needs_action.glob("action_email_*.md"):
            try:
                if f'message_id: "{uid}"' in f.read_text(encoding="utf-8"):
                    return True
            except Exception:
                pass
        return False

    def _fetch_and_process(self, mail, msg_id: bytes, use_uid: bool = False) -> bool:
        """Fetch one message, process if worth acting on. Returns True if action file created."""
        uid = msg_id.decode()

        # Skip if we already have an unprocessed action file for this UID
        if self._is_already_queued(uid):
            self.logger.debug(f"Action file already exists for UID {uid} — skipping")
            return False

        try:
            if use_uid:
                _, msg_data = mail.uid("fetch", msg_id, "(RFC822)")
            else:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)

            sender  = self._decode_header(msg.get("From", ""))
            subject = self._decode_header(msg.get("Subject", ""))
            body    = self._get_body(msg)

            if not self._is_worth_acting_on(sender, subject, body):
                self.logger.info(f"Skipped (automated): {subject[:60]}")
                return False

            action_path = self._process_message(uid, msg, sender, subject, body)
            self.logger.info(f"Action file created: {action_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to process message {uid}: {e}")
            return False

    def check(self) -> int:
        try:
            mail = self._connect()
        except Exception as e:
            self.logger.warning(f"IMAP connect failed: {e}")
            return 0

        new_count   = 0
        last_uid    = self._load_last_uid()
        highest_uid = last_uid

        try:
            mail.select("INBOX")

            if last_uid == 0:
                # First-ever run: start from 7 days ago so we don't process
                # years of old email all at once
                since = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
                self.logger.info(f"First run — scanning emails since {since}")
                _, data = mail.uid("search", None, f'SINCE "{since}"')
            else:
                # Resume exactly where we left off — only emails with UID > last_uid
                self.logger.debug(f"Resuming from UID {last_uid}")
                _, data = mail.uid("search", None, f"UID {last_uid + 1}:*")

            uids = data[0].split()

            if not uids:
                self.logger.debug("No new emails since last check.")
            else:
                self.logger.info(f"{len(uids)} new email(s) to check (UID > {last_uid})")

            for uid_bytes in uids:
                uid_int = int(uid_bytes.decode())

                if self._fetch_and_process(mail, uid_bytes, use_uid=True):
                    new_count += 1

                # Always advance the pointer, even for skipped/automated emails
                if uid_int > highest_uid:
                    highest_uid = uid_int

        finally:
            # Save progress so next restart picks up from here
            if highest_uid > last_uid:
                self._save_last_uid(highest_uid)
                self.logger.debug(f"Progress saved — last UID: {highest_uid}")
            try:
                mail.logout()
            except Exception:
                pass

        return new_count

    def cleanup(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> imaplib.IMAP4_SSL:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(self.address, self.app_password)
        return mail

    def _decode_header(self, value: str) -> str:
        parts = decode_header(value or "")
        result = []
        for part, charset in parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(part)
        return "".join(result)

    def _get_body(self, msg) -> str:
        """Extract plain text body from email."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        body = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        )
                        break
                    except Exception:
                        continue
        else:
            try:
                body = msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or "utf-8", errors="replace"
                )
            except Exception:
                body = ""
        return body[:500]

    def _process_message(self, uid: str, msg, sender: str = "", subject: str = "", body: str = "") -> Path:
        sender   = sender or self._decode_header(msg.get("From", "unknown"))
        subject  = subject or self._decode_header(msg.get("Subject", "(no subject)"))
        date_str = msg.get("Date", "")
        snippet  = body or self._get_body(msg)

        is_sensitive = any(kw in subject.lower() or kw in snippet.lower()
                           for kw in self.SENSITIVE_KEYWORDS)

        received_at  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        safe_subject = subject[:60].replace(" ", "_").replace("/", "-")

        frontmatter = {
            "type":        "email",
            "from":        sender,
            "subject":     subject,
            "date":        date_str,
            "message_id":  uid,
            "received_at": received_at,
            "sensitive":   str(is_sensitive).lower(),
            "status":      "pending",
        }

        body = f"""# Email: {subject}

## Details
- **From:** {sender}
- **Date:** {date_str}
- **Sensitive:** {'YES — route to /Pending_Approval/' if is_sensitive else 'No'}

## Preview
{snippet}

## Action Required
Review this email and take appropriate action. Move to /Done when complete.
"""
        return write_action_file(f"email_{safe_subject}", frontmatter, body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    GmailWatcher().run()
