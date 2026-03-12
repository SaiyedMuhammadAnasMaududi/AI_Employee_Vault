#!/usr/bin/env python3
"""
email_mcp.py - Silver Tier Phase 4: Email MCP Server
=====================================================
Dual-mode script:
  1. MCP stdio server  → run with no args: `python3 email_mcp.py`
                         registers the `send_email` and `draft_email` tools
                         for Claude Code to call via MCP protocol.
  2. CLI send mode     → called by ralph_wrapper.py when an approval file
                         is moved to /Approved/:
                         `python3 email_mcp.py --send --to X --subject Y --body Z`

Uses SMTP (port 465) to send and IMAP to save drafts — both via Gmail App Password.
No OAuth, no secret.json, no token expiry.

Setup (already done if gmail_watcher is working):
    Add to .env:
        GMAIL_ADDRESS=you@gmail.com
        GMAIL_APP_PASSWORD=your16charpassword

Dependencies:
    pip install mcp python-dotenv
"""

import os
import sys
import json
import smtplib
import imaplib
import argparse
import logging
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from dotenv import load_dotenv
except ImportError:
    print("Error: python-dotenv not found. Run: pip install python-dotenv", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths and config
# ---------------------------------------------------------------------------

VAULT_DIR      = Path(__file__).parent
LOGS_DIR       = VAULT_DIR / "Logs"
AGENT_LOG_PATH = LOGS_DIR / "agent_log.md"

load_dotenv(VAULT_DIR / ".env")

GMAIL_ADDRESS  = os.getenv("GMAIL_ADDRESS", "")
GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
DRY_RUN        = os.getenv("DRY_RUN", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),   # stderr so MCP stdout stays clean
        logging.FileHandler(VAULT_DIR / "email_mcp.log"),
    ],
)
logger = logging.getLogger("email_mcp")


def append_log(message: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(AGENT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n## {ts} — {message}\n")


def _check_credentials() -> str | None:
    """Return error string if credentials missing, else None."""
    if not GMAIL_ADDRESS or not GMAIL_PASSWORD:
        return "GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set in .env"
    return None


# ---------------------------------------------------------------------------
# Core send logic
# ---------------------------------------------------------------------------

def _do_send_email(to: str, subject: str, body: str, attachment_path: str = "") -> dict:
    """
    Send an email via Gmail SMTP (SSL, port 465) using App Password.
    Returns {"status": "sent"|"dry_run"|"error", ...}.
    """
    if not to or not subject:
        return {"status": "error", "error": "Missing required fields: to, subject"}

    if DRY_RUN:
        log_msg = f"DRY_RUN email_mcp: to='{to}' subject='{subject}' body_len={len(body)}"
        logger.info(f"[DRY RUN] {log_msg}")
        append_log(log_msg)
        return {"status": "dry_run", "to": to, "subject": subject, "message_id": "dry-run"}

    err = _check_credentials()
    if err:
        return {"status": "error", "error": err}

    try:
        msg = MIMEMultipart()
        msg["From"]    = GMAIL_ADDRESS
        msg["To"]      = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
            smtp.sendmail(GMAIL_ADDRESS, [to], msg.as_string())

        msg_id = f"smtp-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        append_log(f"email_mcp SENT: to='{to}' subject='{subject}' id={msg_id}")
        logger.info(f"Email sent: to={to} subject='{subject}'")
        return {"status": "sent", "to": to, "subject": subject, "message_id": msg_id}

    except smtplib.SMTPAuthenticationError:
        err_msg = "SMTP authentication failed — check GMAIL_APP_PASSWORD in .env"
        logger.error(err_msg)
        return {"status": "error", "error": err_msg}
    except Exception as e:
        logger.error(f"SMTP send failed: {e}")
        return {"status": "error", "error": str(e)}


def _do_draft_email(to: str, subject: str, body: str) -> dict:
    """
    Save email as a Gmail draft via IMAP APPEND to [Gmail]/Drafts.
    Returns {"status": "drafted"|"dry_run_draft"|"error", ...}.
    """
    if DRY_RUN:
        logger.info(f"[DRY RUN] Draft: to={to} subject={subject}")
        return {"status": "dry_run_draft", "to": to, "subject": subject}

    err = _check_credentials()
    if err:
        return {"status": "error", "error": err}

    try:
        msg = MIMEText(body, "plain")
        msg["From"]    = GMAIL_ADDRESS
        msg["To"]      = to
        msg["Subject"] = subject

        with imaplib.IMAP4_SSL("imap.gmail.com", 993) as mail:
            mail.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
            mail.append(
                "[Gmail]/Drafts",
                "\\Draft",
                imaplib.Time2Internaldate(datetime.now().timestamp()),
                msg.as_bytes(),
            )

        draft_id = f"draft-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        append_log(f"email_mcp DRAFT: to='{to}' subject='{subject}' draft_id={draft_id}")
        logger.info(f"Draft saved to Gmail Drafts: to={to}")
        return {"status": "drafted", "draft_id": draft_id, "to": to, "subject": subject}

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP draft failed: {e}")
        return {"status": "error", "error": str(e)}
    except Exception as e:
        logger.error(f"Draft failed: {e}")
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# MCP server mode
# ---------------------------------------------------------------------------

def run_mcp_server() -> None:
    """Start the MCP stdio server exposing email tools to Claude Code."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "Error: 'mcp' library not found. Run: pip install mcp",
            file=sys.stderr,
        )
        sys.exit(1)

    server = FastMCP("email-mcp")

    @server.tool()
    def send_email(to: str, subject: str, body: str, attachment_path: str = "") -> str:
        """
        Send an email via Gmail SMTP using App Password.
        If DRY_RUN=true in .env, logs only — no email is sent.

        Args:
            to:              Recipient email address.
            subject:         Email subject line.
            body:            Plain-text email body.
            attachment_path: Unused (reserved for future use).
        """
        result = _do_send_email(to, subject, body, attachment_path)
        return json.dumps(result)

    @server.tool()
    def draft_email(to: str, subject: str, body: str) -> str:
        """
        Save an email as a Gmail draft for human review before sending.

        Args:
            to:      Recipient email address.
            subject: Email subject line.
            body:    Plain-text email body.
        """
        result = _do_draft_email(to, subject, body)
        return json.dumps(result)

    @server.tool()
    def check_dry_run_status() -> str:
        """Return whether the server is in dry-run mode."""
        return json.dumps({"dry_run": DRY_RUN, "vault": str(VAULT_DIR),
                           "gmail_address": GMAIL_ADDRESS})

    logger.info(f"email-mcp server starting (dry_run={DRY_RUN}, address={GMAIL_ADDRESS})")
    server.run(transport="stdio")


# ---------------------------------------------------------------------------
# CLI mode (called by ralph_wrapper.py or for testing)
# ---------------------------------------------------------------------------

def run_cli() -> None:
    mode = sys.argv[1]  # "--send" or "--draft"

    parser = argparse.ArgumentParser(description=f"email_mcp {mode}")
    parser.add_argument("--to",         default="")
    parser.add_argument("--subject",    default="")
    parser.add_argument("--body",       default="")
    parser.add_argument("--attachment", default="")
    args = parser.parse_args(sys.argv[2:])

    if mode == "--send":
        if not args.to:
            print("Error: --to is required for --send", file=sys.stderr)
            sys.exit(1)
        result = _do_send_email(args.to, args.subject, args.body, args.attachment)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] in ("sent", "dry_run") else 1)

    elif mode == "--draft":
        if not args.to:
            print("Error: --to is required for --draft", file=sys.stderr)
            sys.exit(1)
        result = _do_draft_email(args.to, args.subject, args.body)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] in ("drafted", "dry_run_draft") else 1)

    else:
        print(f"Unknown mode: {mode}. Use --send or --draft.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--send", "--draft"):
        run_cli()
    else:
        run_mcp_server()
