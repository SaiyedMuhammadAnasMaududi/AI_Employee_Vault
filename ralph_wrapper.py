#!/usr/bin/env python3
"""
ralph_wrapper.py - Silver Tier Phase 4 Orchestrator (Ralph Wiggum Pattern)
===========================================================================
Two watchers run in parallel:

  Watcher 1 — /Needs_Action/ (Ralph loop)
    New .md file → run Claude Code CLI reasoning loop (max 10 iterations)
    Claude uses skills to create Plan.md, write Pending_Approval files for
    sensitive actions, and output <promise>TASK_COMPLETE</promise> when done.

  Watcher 2 — /Approved/ (MCP executor)
    Human moves Pending_Approval file to /Approved/ → parse action_type
    → call email_mcp.py (or log for linkedin_post) → move to /Done/.

HITL flow:
  task → Claude writes /Pending_Approval/action.md → loop pauses →
  Human moves to /Approved/ → ApprovedHandler executes MCP → loop resumes.

Dependencies:
    pip install watchdog python-dotenv
    (No Anthropic SDK — uses Claude Code CLI directly)

Run:
    python3 ralph_wrapper.py
"""

import os
import re
import sys
import time
import shutil
import logging
import subprocess
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
except ImportError:
    print("Error: python-dotenv not found. Run: pip install python-dotenv")
    sys.exit(1)

try:
    from watchdog.observers.polling import PollingObserver
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("Error: watchdog not found. Run: pip install watchdog")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

VAULT_DIR        = Path(__file__).parent
NEEDS_ACTION_DIR = VAULT_DIR / "Needs_Action"
PLANS_DIR        = VAULT_DIR / "Plans"
PENDING_DIR      = VAULT_DIR / "Pending_Approval"
APPROVED_DIR     = VAULT_DIR / "Approved"
REJECTED_DIR     = VAULT_DIR / "Rejected"
DONE_DIR         = VAULT_DIR / "Done"
LOGS_DIR         = VAULT_DIR / "Logs"
SKILLS_DIR       = VAULT_DIR / ".claude" / "skills"
HANDBOOK_PATH    = VAULT_DIR / "Company_Handbook.md"
AGENT_LOG_PATH   = LOGS_DIR / "agent_log.md"

load_dotenv(VAULT_DIR / ".env")
POLL_INTERVAL = int(os.getenv("ORCHESTRATOR_POLL_INTERVAL", "10"))

# Tracks email UIDs we have already replied to — prevents duplicate sends
REPLIED_IDS_FILE = VAULT_DIR / "gmail_replied_ids.txt"


def _load_replied_ids() -> set:
    try:
        return set(REPLIED_IDS_FILE.read_text(encoding="utf-8").splitlines())
    except Exception:
        return set()


def _save_replied_id(uid: str) -> None:
    try:
        with open(REPLIED_IDS_FILE, "a", encoding="utf-8") as f:
            f.write(uid + "\n")
    except Exception as e:
        logger.warning(f"Could not save replied ID: {e}")

# Ralph Wiggum constants
COMPLETION_PROMISE   = "<promise>TASK_COMPLETE</promise>"
MAX_ITERATIONS       = 10
CLAUDE_TIMEOUT       = 300   # seconds per Claude call (general tasks)
EMAIL_CLAUDE_TIMEOUT = 200   # seconds per Claude call (email tasks — fast path)
EMAIL_MAX_ITERATIONS = 2     # emails should be done in 1-2 iterations
APPROVAL_POLL_SEC    = 15    # seconds between /Approved/ checks

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(VAULT_DIR / "ralph_wrapper.log"),
    ],
)
logger = logging.getLogger("ralph_wrapper")


def append_log(message: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(AGENT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n## {ts} — {message}\n")


# ---------------------------------------------------------------------------
# Frontmatter parser (no yaml dependency)
# ---------------------------------------------------------------------------

def parse_frontmatter(content: str) -> dict:
    """Extract key:value pairs from YAML frontmatter block."""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    result = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip().strip('"').strip("'")
    return result


# ---------------------------------------------------------------------------
# Skill / handbook loaders
# ---------------------------------------------------------------------------

def _read(path: Path, label: str = "") -> str:
    return path.read_text(encoding="utf-8") if path.exists() else f"({label or path.name} not found)"


def build_prompt(task_file: Path, iteration: int, prev_output: str) -> str:
    handbook     = _read(HANDBOOK_PATH, "Company_Handbook.md")
    skill_plan   = _read(SKILLS_DIR / "create_plan.md", "create_plan")
    skill_li     = _read(SKILLS_DIR / "draft_linkedin_post.md", "draft_linkedin_post")
    skill_ra     = _read(SKILLS_DIR / "read_needs_action.md", "read_needs_action")
    skill_approve= _read(SKILLS_DIR / "approve_action.md", "approve_action")
    task_content = _read(task_file, "task file")

    context_section = ""
    if iteration > 1 and prev_output:
        context_section = f"""
## Previous Iteration Output (iteration {iteration - 1})
{prev_output[-3000:]}

Continue from where you left off. Do NOT repeat completed steps.
"""

    return f"""You are the AI Employee orchestrator for this personal business vault.
Today: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Vault directory: {VAULT_DIR}
Iteration: {iteration} of {MAX_ITERATIONS}

---
## Company Rules (from Company_Handbook.md)
{handbook}

---
## Skills Reference

### read_needs_action
{skill_ra}

### create_plan
{skill_plan}

### draft_linkedin_post
{skill_li}

### approve_action
{skill_approve}

---
## YOUR TASK (Iteration {iteration})

A new task file appeared in /Needs_Action/:
  File: {task_file.name}

Content:
{task_content}

---
## Execution Steps

1. **Classify** the task:
   - SENSITIVE: payments >$50, legal, PII, new external contact → requires HITL
   - BUSINESS/SALES: service launch, product, partnership, achievement → LinkedIn draft

2. **Create Plan.md** in /Plans/ using the create_plan skill format.
   Filename: plan_<task_stem>_<unix_epoch>.md
   Include YAML frontmatter: source_task, created_at, sensitive, business_post, status.

3. **For SENSITIVE or EMAIL actions** → create /Pending_Approval/<name>.md
   Use this EXACT frontmatter format:
   ---
   action_type: "send_email"
   to: "<recipient>"
   subject: "<subject>"
   body: "<email body>"
   reason: "<why approval is needed>"
   sensitive: "true"
   created_at: "<timestamp>"
   status: "pending"
   ---

4. **For BUSINESS/SALES** → add LinkedIn post draft to Plan.md AND create
   /Pending_Approval/<name>.md with:
   ---
   action_type: "linkedin_post"
   post_content: "<the full post text>"
   reason: "LinkedIn post requires human approval before publishing"
   sensitive: "false"
   created_at: "<timestamp>"
   status: "pending"
   ---

5. **Move original task** → /Done/{task_file.name} when all plans and
   approval files are written.

6. **Output** {COMPLETION_PROMISE} on its own line when ALL steps are done.
   Do NOT output it before moving the task file to /Done/.

{context_section}
IMPORTANT: Use your file tools (Read, Write, Bash) to actually DO the steps.
Do NOT just describe what you would do — execute each step with your tools.
Output {COMPLETION_PROMISE} only after all files are written and task moved to /Done/.
"""


# ---------------------------------------------------------------------------
# Fast email prompt — short and focused, no handbook bloat
# ---------------------------------------------------------------------------

def build_email_prompt(task_file: Path, task_content: str) -> str:
    """
    Ultra-minimal prompt: Claude ONLY generates the reply text.
    Ralph writes all files himself in Python (no tool calls = fast).
    """
    return f"""You are an AI email assistant. Read the email below and write a short, professional reply.

{task_content}

Rules:
- Be concise and helpful (3-5 sentences max).
- If requesting invoice/payment info, acknowledge urgently and say details will follow shortly.
- Sign off as: AI Assistant

Output ONLY the reply text. No subject line, no "Here is my reply:", no extra commentary.
Just the reply body itself."""


# ---------------------------------------------------------------------------
# HITL pause: wait for Pending_Approval files to resolve
# ---------------------------------------------------------------------------

def snapshot_pending() -> set[str]:
    return {f.name for f in PENDING_DIR.glob("*.md")} if PENDING_DIR.exists() else set()


def wait_for_hitl(new_pending: set[str]) -> dict[str, str]:
    """
    Pause loop until all newly-created Pending_Approval files are resolved.
    ApprovedHandler (below) will execute the actions as files land in /Approved/.
    Returns {filename: "approved"|"rejected"}.
    """
    logger.info(f"[HITL] Pausing — {len(new_pending)} file(s) need human review:")
    for name in new_pending:
        logger.info(f"  → Pending_Approval/{name}")
    logger.info("[HITL] Move file(s) to /Approved/ or /Rejected/ to continue...")
    append_log(f"ralph_wrapper HITL PAUSE: awaiting {new_pending}")

    outcomes: dict[str, str] = {}

    while set(outcomes.keys()) < new_pending:
        for name in new_pending - set(outcomes.keys()):
            if (APPROVED_DIR / name).exists():
                outcomes[name] = "approved"
                logger.info(f"[HITL] ✓ Approved: {name}")
            elif (REJECTED_DIR / name).exists():
                outcomes[name] = "rejected"
                logger.info(f"[HITL] ✗ Rejected: {name}")
        if set(outcomes.keys()) < new_pending:
            logger.info(f"[HITL] Still waiting: {new_pending - set(outcomes.keys())}")
            time.sleep(APPROVAL_POLL_SEC)

    logger.info(f"[HITL] All resolved: {outcomes}")
    append_log(f"ralph_wrapper HITL RESOLVED: {outcomes}")
    return outcomes


# ---------------------------------------------------------------------------
# Ralph Wiggum loop
# ---------------------------------------------------------------------------

def _run_email_fast_path(task_file: Path) -> bool:
    """
    Fast email handler using Qwen CLI:
    1. Ask Qwen for reply text only (~5s, no session conflicts)
    2. Ralph creates the Pending_Approval file directly in Python
    3. Ralph moves task to Done
    Returns True on success.
    """
    task_content = task_file.read_text(encoding="utf-8") if task_file.exists() else ""
    fm           = parse_frontmatter(task_content)
    sender_email = fm.get("from", "").strip('"')
    subject      = fm.get("subject", "(no subject)").strip('"')
    ts           = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uid          = fm.get("message_id", "").strip('"')

    # Duplicate guard — never send two replies to the same email UID
    if uid and uid in _load_replied_ids():
        logger.info(f"  Already replied to UID {uid} — skipping duplicate, moving to Done")
        _move_to_done(task_file)
        return True

    # Extract email address from "Name <email>" format
    import re as _re
    match = _re.search(r"<([^>]+)>", sender_email)
    to_addr = match.group(1) if match else sender_email

    prompt = build_email_prompt(task_file, task_content)

    logger.info(f"  Calling Qwen for reply text...")

    try:
        result = subprocess.run(
            [
                "qwen",
                prompt,
                "--output-format", "text",
                "--approval-mode", "yolo",   # auto-approve, text only
            ],
            cwd=str(VAULT_DIR),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=EMAIL_CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error(f"  Qwen timed out after {EMAIL_CLAUDE_TIMEOUT}s")
        append_log(f"ralph_wrapper TIMEOUT: email '{task_file.name}'")
        return False

    reply_text = result.stdout.strip()
    if not reply_text or result.returncode != 0:
        logger.error(f"  Qwen failed. RC={result.returncode}")
        logger.error(f"  STDOUT: {result.stdout[:300]}")
        logger.error(f"  STDERR: {result.stderr[:300]}")
        return False

    logger.info(f"  Reply drafted ({len(reply_text)} chars). Sending automatically...")

    # Send directly via email_mcp.py — no approval step
    send_result = subprocess.run(
        [
            "python3", str(VAULT_DIR / "email_mcp.py"),
            "--send",
            "--to", to_addr,
            "--subject", f"Re: {subject}",
            "--body", reply_text,
        ],
        cwd=str(VAULT_DIR),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )

    if send_result.returncode != 0:
        logger.error(f"  Send failed. RC={send_result.returncode} ERR={send_result.stderr[:200]}")
        append_log(f"ralph_wrapper SEND ERROR: '{task_file.name}' — {send_result.stderr[:100]}")
        return False

    logger.info(f"  Email sent to {to_addr} ✓")
    logger.info(f"  Response: {send_result.stdout.strip()[:150]}")
    append_log(f"ralph_wrapper: email auto-sent to '{to_addr}' re '{subject}'")

    # Mark this UID as replied so we never send again even if file reappears
    if uid:
        _save_replied_id(uid)

    # Archive a copy in Done for record-keeping
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    record_name = f"sent_email_{task_file.stem}_{int(datetime.now().timestamp())}.md"
    record_content = f"""---
action_type: "send_email"
to: "{to_addr}"
subject: "Re: {subject}"
sent_at: "{ts}"
status: "sent"
---

## Original Email
**From:** {sender_email}
**Subject:** {subject}

## Reply Sent
{reply_text}
"""
    (DONE_DIR / record_name).write_text(record_content, encoding="utf-8")

    _move_to_done(task_file)
    return True


def _is_email_task(task_file: Path) -> bool:
    try:
        fm = parse_frontmatter(task_file.read_text(encoding="utf-8"))
        return fm.get("type", "").lower() == "email"
    except Exception:
        return False


def _is_odoo_task(task_file: Path) -> bool:
    try:
        fm = parse_frontmatter(task_file.read_text(encoding="utf-8"))
        t = fm.get("type", "").lower()
        at = fm.get("action_type", "").lower()
        return t in ("odoo_invoice", "odoo_payment", "odoo_balance") or \
               at in ("odoo_create_invoice", "odoo_post_payment", "odoo_get_balance")
    except Exception:
        return False


def _is_social_task(task_file: Path) -> bool:
    try:
        fm = parse_frontmatter(task_file.read_text(encoding="utf-8"))
        t = fm.get("type", "").lower()
        at = fm.get("action_type", "").lower()
        return t == "social_post" or at == "meta_post"
    except Exception:
        return False


def _run_odoo_fast_path(task_file: Path) -> bool:
    """Direct Odoo handler — no Claude loop needed. Parses frontmatter and calls odoo_mcp."""
    content = task_file.read_text(encoding="utf-8")
    fm      = parse_frontmatter(content)
    action  = fm.get("action_type", fm.get("type", "odoo_create_invoice")).lower()
    partner = fm.get("partner", fm.get("customer", "")).strip('"')
    amount  = float(fm.get("amount", 0))
    desc    = fm.get("description", fm.get("product", "Service")).strip('"')
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"  [FAST PATH] Odoo task — action={action} partner={partner} amount={amount}")

    if action in ("odoo_create_invoice", "odoo_invoice"):
        if amount > 50:
            # HITL — create Pending_Approval and pause
            import time as _time
            PENDING_DIR.mkdir(parents=True, exist_ok=True)
            epoch    = int(_time.time())
            fname    = f"approval_odoo_create_invoice_{epoch}.md"
            content_pa = f"""---
action_type: "odoo_create_invoice"
partner: "{partner}"
amount: "{amount}"
description: "{desc}"
reason: "Invoice amount ${amount:.2f} exceeds $50 threshold — human approval required"
sensitive: "true"
created_at: "{ts}"
status: "pending"
---

# Odoo Invoice Requires Approval

**Partner:** {partner}
**Amount:** ${amount:.2f}
**Description:** {desc}

Move to /Approved/ to create invoice in Odoo, or /Rejected/ to cancel.
"""
            (PENDING_DIR / fname).write_text(content_pa, encoding="utf-8")
            logger.info(f"  [HITL] Pending_Approval created: {fname}")
            append_log(f"ralph_wrapper: HITL pending for odoo_create_invoice partner={partner} amount={amount}")
            _move_to_done(task_file)
            return True
        else:
            # Auto-proceed — below threshold
            result = subprocess.run(
                ["python3", str(VAULT_DIR / "odoo_mcp.py"),
                 "--action", "create_invoice",
                 "--partner", partner,
                 "--amount", str(amount),
                 "--description", desc,
                 "--force"],
                capture_output=True, text=True, timeout=60, cwd=str(VAULT_DIR)
            )
            logger.info(f"  Odoo result: {result.stdout.strip()[:200]}")
            append_log(f"ralph_wrapper: odoo_create_invoice auto partner={partner} amount={amount}")
            _move_to_done(task_file)
            return True

    elif action in ("odoo_post_payment", "odoo_payment"):
        invoice_id = int(fm.get("invoice_id", 0))
        if amount > 50:
            import time as _time
            PENDING_DIR.mkdir(parents=True, exist_ok=True)
            epoch  = int(_time.time())
            fname  = f"approval_odoo_post_payment_{epoch}.md"
            content_pa = f"""---
action_type: "odoo_post_payment"
invoice_id: "{invoice_id}"
amount: "{amount}"
reason: "Payment ${amount:.2f} exceeds $50 threshold"
sensitive: "true"
created_at: "{ts}"
status: "pending"
---

Move to /Approved/ to register payment, or /Rejected/ to cancel.
"""
            (PENDING_DIR / fname).write_text(content_pa, encoding="utf-8")
            logger.info(f"  [HITL] Pending_Approval created: {fname}")
            _move_to_done(task_file)
            return True

    elif action in ("odoo_get_balance", "odoo_balance"):
        result = subprocess.run(
            ["python3", str(VAULT_DIR / "odoo_mcp.py"), "--action", "get_balance"],
            capture_output=True, text=True, timeout=30, cwd=str(VAULT_DIR)
        )
        logger.info(f"  Balance: {result.stdout.strip()[:200]}")
        append_log(f"ralph_wrapper: odoo_get_balance → {result.stdout.strip()[:100]}")
        _move_to_done(task_file)
        return True

    _move_to_done(task_file)
    return True


def _run_social_fast_path(task_file: Path) -> bool:
    """Direct Meta Social handler — creates Pending_Approval (always requires HITL)."""
    content  = task_file.read_text(encoding="utf-8")
    fm       = parse_frontmatter(content)
    platform = fm.get("platform", "facebook").strip('"')
    message  = fm.get("content", fm.get("message", "")).strip('"')
    ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"  [FAST PATH] Social task — platform={platform}")

    import time as _time
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    epoch = int(_time.time())
    fname = f"approval_meta_post_{epoch}.md"
    content_pa = f"""---
action_type: "meta_post"
platform: "{platform}"
message: "{message}"
reason: "Meta posts always require human approval before publishing"
sensitive: "true"
created_at: "{ts}"
status: "pending"
---

# Meta Social Post Requires Approval

**Platform:** {platform}
**Message:** {message}

Move to /Approved/ to post (dry-run until token set), or /Rejected/ to cancel.
"""
    (PENDING_DIR / fname).write_text(content_pa, encoding="utf-8")
    logger.info(f"  [HITL] Pending_Approval created: {fname}")
    append_log(f"ralph_wrapper: meta_post HITL pending platform={platform}")
    _move_to_done(task_file)
    return True


def run_ralph_loop(task_file: Path) -> bool:
    """
    Run Claude Code CLI in an iteration loop until TASK_COMPLETE or max iters.
    Uses fast paths for known task types (email, odoo, social).
    Returns True on success.
    """
    logger.info(f"Starting Ralph loop → {task_file.name}")
    append_log(f"ralph_wrapper: Ralph loop started for '{task_file.name}'")

    if _is_email_task(task_file):
        logger.info("  [FAST PATH] Email task — Qwen CLI, Ralph writes files")
        return _run_email_fast_path(task_file)

    if _is_odoo_task(task_file):
        logger.info("  [FAST PATH] Odoo task — direct MCP call")
        return _run_odoo_fast_path(task_file)

    if _is_social_task(task_file):
        logger.info("  [FAST PATH] Social task — direct HITL pending")
        return _run_social_fast_path(task_file)

    is_email   = False
    max_iters  = MAX_ITERATIONS
    timeout    = CLAUDE_TIMEOUT

    prev_output    = ""
    pending_before = snapshot_pending()

    for iteration in range(1, max_iters + 1):
        logger.info(f"  ── Iteration {iteration}/{max_iters} ──")

        prompt = build_prompt(task_file, iteration, prev_output)

        try:
            result = subprocess.run(
                [
                    "qwen",
                    prompt,
                    "--output-format", "text",
                    "--approval-mode", "yolo",
                ],
                cwd=str(VAULT_DIR),
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.error(f"  Qwen timed out after {timeout}s")
            append_log(f"ralph_wrapper TIMEOUT: '{task_file.name}' iter {iteration}")
            return False
        except FileNotFoundError:
            logger.error("  'qwen' CLI not found — is Qwen installed?")
            sys.exit(1)

        output = result.stdout.strip()

        if result.returncode != 0:
            logger.warning(f"  Qwen exited {result.returncode}: {result.stderr[:300]}")

        logger.info(f"  [Qwen] Preview: {output[:400].replace(chr(10), ' ')}...")

        # ── HITL check ──────────────────────────────────────────────────────
        pending_after = snapshot_pending()
        new_pending   = pending_after - pending_before

        if new_pending:
            # ApprovedHandler will execute the action when human approves
            outcomes = wait_for_hitl(new_pending)
            rejected_all = all(v == "rejected" for v in outcomes.values())

            if rejected_all:
                logger.info("  All actions rejected — closing task.")
                _move_to_done(task_file)
                append_log(f"ralph_wrapper: '{task_file.name}' rejected → /Done/")
                return True

            approval_ctx = "\n".join(
                f"  - {f} → {d.upper()}" for f, d in outcomes.items()
            )
            prev_output    = output + f"\n\nHuman review complete:\n{approval_ctx}"
            pending_before = snapshot_pending()
            continue

        # ── Completion check ─────────────────────────────────────────────────
        if COMPLETION_PROMISE in output:
            logger.info(f"  Task complete after {iteration} iteration(s).")
            append_log(f"ralph_wrapper: '{task_file.name}' done in {iteration} iter(s)")
            return True

        prev_output = output
        logger.info(f"  No completion promise — continuing to iteration {iteration + 1}")

    logger.warning(f"  Max iterations ({MAX_ITERATIONS}) reached.")
    append_log(f"ralph_wrapper INCOMPLETE: '{task_file.name}' hit max iterations")
    return False


def _move_to_done(task_file: Path) -> None:
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    if task_file.exists():
        shutil.move(str(task_file), str(DONE_DIR / task_file.name))
        logger.info(f"  Moved '{task_file.name}' → /Done/")


# ---------------------------------------------------------------------------
# Watcher 1: Needs_Action → Ralph loop
# ---------------------------------------------------------------------------

class NeedsActionHandler(FileSystemEventHandler):
    def __init__(self):
        self._in_progress: set[str] = set()

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".md" or str(path) in self._in_progress:
            return

        self._in_progress.add(str(path))
        logger.info(f"[NeedsAction] New task: {path.name}")
        time.sleep(2)  # let file finish writing

        if not path.exists():
            self._in_progress.discard(str(path))
            return

        try:
            success = run_ralph_loop(path)
            logger.info(f"[NeedsAction] Loop done [{'OK' if success else 'INCOMPLETE'}]: {path.name}")
        except Exception as e:
            logger.error(f"[NeedsAction] Error: {e}")
            append_log(f"ralph_wrapper ERROR: '{path.name}' — {e}")
        finally:
            self._in_progress.discard(str(path))


# ---------------------------------------------------------------------------
# Watcher 2: Approved → MCP executor
# ---------------------------------------------------------------------------

def execute_approved_action(approval_file: Path) -> None:
    """Parse an /Approved/ file and execute its action via email_mcp.py or log."""
    content     = approval_file.read_text(encoding="utf-8")
    fm          = parse_frontmatter(content)
    action_type = fm.get("action_type", "").lower().strip('"')

    logger.info(f"[Approved] Executing: action_type='{action_type}' file='{approval_file.name}'")

    if action_type == "send_email":
        to      = fm.get("to", "").strip('"')
        subject = fm.get("subject", "").strip('"')
        body    = fm.get("body", "").strip('"')

        if not to:
            logger.error("[Approved] Missing 'to' field — cannot send email.")
            append_log(f"approve_action ERROR: missing 'to' in {approval_file.name}")
        else:
            result = subprocess.run(
                [
                    "python3", str(VAULT_DIR / "email_mcp.py"),
                    "--send",
                    "--to",      to,
                    "--subject", subject,
                    "--body",    body,
                ],
                cwd=str(VAULT_DIR),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                logger.info(f"[Approved] Email result: {result.stdout.strip()[:200]}")
                append_log(f"approve_action: send_email to='{to}' subject='{subject}' → OK")
            else:
                logger.error(f"[Approved] Email failed: {result.stderr[:300]}")
                append_log(f"approve_action ERROR: email to '{to}' failed — {result.stderr[:200]}")

    elif action_type in ("odoo_create_invoice", "odoo_invoice"):
        import json as _json
        params_raw = fm.get("params", "{}").strip('"').replace('\\"', '"')
        try:
            params = _json.loads(params_raw)
        except Exception:
            params = {}
        partner     = params.get("partner", fm.get("partner", "").strip('"'))
        amount      = float(params.get("amount", fm.get("amount", 0)))
        description = params.get("description", fm.get("description", "Service").strip('"'))
        result = subprocess.run(
            ["python3", str(VAULT_DIR / "odoo_mcp.py"),
             "--action", "create_invoice",
             "--partner", partner,
             "--amount", str(amount),
             "--description", description,
             "--force"],   # already approved by human — skip HITL re-check
            capture_output=True, text=True, timeout=60, cwd=str(VAULT_DIR)
        )
        if result.returncode == 0:
            logger.info(f"[Approved] Odoo invoice: {result.stdout.strip()[:200]}")
            append_log(f"approve_action: odoo create_invoice partner='{partner}' amount={amount} → OK")
        else:
            logger.error(f"[Approved] Odoo invoice failed: {result.stderr[:200]}")
            append_log(f"approve_action ERROR: odoo create_invoice failed — {result.stderr[:100]}")

    elif action_type in ("odoo_post_payment", "odoo_payment"):
        import json as _json
        params_raw = fm.get("params", "{}").strip('"').replace('\\"', '"')
        try:
            params = _json.loads(params_raw)
        except Exception:
            params = {}
        invoice_id = int(params.get("invoice_id", fm.get("invoice_id", 0)))
        amount     = float(params.get("amount", fm.get("amount", 0)))
        result = subprocess.run(
            ["python3", str(VAULT_DIR / "odoo_mcp.py"),
             "--action", "post_payment",
             "--invoice-id", str(invoice_id),
             "--amount", str(amount),
             "--force"],   # already approved by human — skip HITL re-check
            capture_output=True, text=True, timeout=60, cwd=str(VAULT_DIR)
        )
        if result.returncode == 0:
            logger.info(f"[Approved] Odoo payment: {result.stdout.strip()[:200]}")
            append_log(f"approve_action: odoo post_payment invoice={invoice_id} amount={amount} → OK")
        else:
            logger.error(f"[Approved] Odoo payment failed: {result.stderr[:200]}")
            append_log(f"approve_action ERROR: odoo post_payment failed — {result.stderr[:100]}")

    elif action_type == "meta_post":
        platform = fm.get("platform", "facebook").strip('"')
        message  = fm.get("message", fm.get("post_content", "")).strip('"').replace("\\n", "\n")
        image_url = fm.get("image_url", "").strip('"')
        action_arg = "post_facebook" if platform == "facebook" else "post_instagram"
        cmd = ["python3", str(VAULT_DIR / "meta_social_mcp.py"),
               "--action", action_arg, "--message", message]
        if image_url:
            cmd += ["--image-url", image_url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(VAULT_DIR))
        if result.returncode == 0:
            logger.info(f"[Approved] Meta post ({platform}): {result.stdout.strip()[:200]}")
            append_log(f"approve_action: meta_post platform={platform} → OK")
        else:
            logger.error(f"[Approved] Meta post failed: {result.stderr[:200]}")
            append_log(f"approve_action ERROR: meta_post failed — {result.stderr[:100]}")

    elif action_type == "linkedin_post":
        post = fm.get("post_content", "").strip('"').replace("\\n", "\n")
        if not post:
            # Try reading from body section
            import re as _re
            bm = _re.search(r"## Post Content\n(.*?)(\n##|$)", content, _re.DOTALL)
            if bm:
                post = bm.group(1).strip()

        if post:
            li_result = subprocess.run(
                [
                    "python3", str(VAULT_DIR / "linkedin_watcher.py"),
                    "--post",
                    "--content", post,
                ],
                cwd=str(VAULT_DIR),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if li_result.returncode == 0:
                logger.info(f"[Approved] LinkedIn post published.")
                append_log(f"approve_action: linkedin_post PUBLISHED — {post[:100]}")
            else:
                logger.error(f"[Approved] LinkedIn post failed: {li_result.stderr[:200]}")
                append_log(f"approve_action: linkedin_post FAILED — {li_result.stderr[:150]}")
        else:
            logger.warning("[Approved] No post_content found in LinkedIn approval file.")
            append_log("approve_action: linkedin_post APPROVED but no content found")

    else:
        logger.warning(f"[Approved] Unknown action_type: '{action_type}'")
        append_log(f"approve_action WARN: unknown action_type '{action_type}'")

    # Move approval file to /Done/
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    dest = DONE_DIR / approval_file.name
    shutil.move(str(approval_file), str(dest))
    logger.info(f"[Approved] Moved approval file → /Done/{approval_file.name}")


class ApprovedHandler(FileSystemEventHandler):
    """Executes actions when human moves files to /Approved/."""

    def __init__(self):
        self._processing: set[str] = set()

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".md" or str(path) in self._processing:
            return

        self._processing.add(str(path))
        logger.info(f"[Approved] File approved by human: {path.name}")
        time.sleep(1)

        try:
            execute_approved_action(path)
        except Exception as e:
            logger.error(f"[Approved] Execution error: {e}")
            append_log(f"approve_action ERROR: {path.name} — {e}")
        finally:
            self._processing.discard(str(path))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _maybe_run_weekly_briefing() -> None:
    """Run the Monday Morning CEO Briefing on Sunday at 10 PM, once per week."""
    now = datetime.now()
    if now.weekday() != 6 or now.hour != 22:   # Sunday = 6, 10 PM = 22
        return

    # Use Monday's date as the briefing key (briefing covers the coming week)
    from datetime import timedelta
    monday     = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    briefing_f = VAULT_DIR / "Briefings" / f"{monday}_ceo_briefing.md"
    if briefing_f.exists():
        return  # already ran this week

    logger.info("[Briefing] Sunday 10 PM — generating weekly CEO briefing...")
    append_log("ralph_wrapper: weekly CEO briefing triggered")

    try:
        # Gather data
        balance_raw = subprocess.run(
            ["python3", str(VAULT_DIR / "odoo_mcp.py"), "--action", "get_balance"],
            capture_output=True, text=True, timeout=30, cwd=str(VAULT_DIR)
        ).stdout.strip() or '{"status":"unavailable"}'

        social_raw = subprocess.run(
            ["python3", str(VAULT_DIR / "meta_social_mcp.py"),
             "--action", "generate_summary", "--period", "week"],
            capture_output=True, text=True, timeout=30, cwd=str(VAULT_DIR)
        ).stdout.strip() or '{"status":"unavailable"}'

        li_posts = subprocess.run(
            ["grep", "-c", "Auto-post published", str(VAULT_DIR / "linkedin_watcher.log")],
            capture_output=True, text=True
        ).stdout.strip() or "0"

        done_emails = len(list((VAULT_DIR / "Done").glob("action_email_*.md")))

        goals = ""
        goals_f = VAULT_DIR / "Business_Goals.md"
        if goals_f.exists():
            goals = goals_f.read_text(encoding="utf-8")[:1500]

        odoo_log = ""
        odoo_log_f = VAULT_DIR / "Logs" / "odoo_actions.md"
        if odoo_log_f.exists():
            odoo_log = odoo_log_f.read_text(encoding="utf-8")[-1000:]

        prompt = f"""Write a concise Monday Morning CEO Briefing (200-300 words) based on this data:

BUSINESS GOALS:
{goals}

FINANCIAL STATUS (Odoo):
{balance_raw}

SOCIAL MEDIA (this week):
LinkedIn posts: {li_posts}
Meta activity: {social_raw[:300]}

EMAIL ACTIVITY:
Emails processed this month: {done_emails}

ODOO ACTIONS (recent):
{odoo_log[:500]}

Format:
# CEO Briefing — Week of {monday}
## Executive Summary
## Key Metrics
## Wins This Week
## Actions Needed
## Goals Progress

Output ONLY the briefing markdown."""

        result = subprocess.run(
            ["qwen", prompt, "--output-format", "text", "--approval-mode", "yolo"],
            capture_output=True, text=True, timeout=120, cwd=str(VAULT_DIR)
        )
        briefing_text = result.stdout.strip() if result.returncode == 0 else ""

        if not briefing_text:
            briefing_text = f"""# CEO Briefing — Week of {monday}

*Auto-generation failed — manual review needed.*

## Key Metrics
- Odoo balance: {balance_raw[:200]}
- LinkedIn posts this week: {li_posts}
- Emails processed: {done_emails}

Generated: {now.strftime("%Y-%m-%d %H:%M:%S")}
"""

        (VAULT_DIR / "Briefings").mkdir(exist_ok=True)
        briefing_f.write_text(briefing_text, encoding="utf-8")
        logger.info(f"[Briefing] Saved → Briefings/{monday}_ceo_briefing.md")
        append_log(f"ralph_wrapper: CEO briefing saved → {briefing_f.name}")

    except Exception as e:
        logger.error(f"[Briefing] Generation failed: {e}")
        append_log(f"ralph_wrapper ERROR: briefing generation failed — {e}")


def main():
    for d in [NEEDS_ACTION_DIR, PLANS_DIR, PENDING_DIR, APPROVED_DIR,
              REJECTED_DIR, DONE_DIR, LOGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Silver Tier Phase 4 — Ralph Wiggum + MCP Orchestrator")
    logger.info(f"  Watcher 1 (Ralph): {NEEDS_ACTION_DIR}")
    logger.info(f"  Watcher 2 (MCP):   {APPROVED_DIR}")
    logger.info(f"  Completion:        {COMPLETION_PROMISE}")
    logger.info(f"  Max iterations:    {MAX_ITERATIONS}")
    logger.info(f"  Approval poll:     every {APPROVAL_POLL_SEC}s")
    logger.info(f"  Poll interval:     {POLL_INTERVAL}s")
    logger.info("=" * 60)

    # Watcher 1: Needs_Action → Ralph reasoning loop
    needs_observer = PollingObserver()
    needs_observer.schedule(NeedsActionHandler(), str(NEEDS_ACTION_DIR), recursive=False)
    needs_observer.start()
    logger.info("Watcher 1 active: /Needs_Action/ → Ralph loop")

    # Watcher 2: Approved → MCP executor
    approved_observer = PollingObserver()
    approved_observer.schedule(ApprovedHandler(), str(APPROVED_DIR), recursive=False)
    approved_observer.start()
    logger.info("Watcher 2 active: /Approved/ → MCP executor")
    logger.info("Ready. Ctrl+C to stop.")

    try:
        while True:
            time.sleep(POLL_INTERVAL)
            _maybe_run_weekly_briefing()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        needs_observer.stop()
        approved_observer.stop()

    needs_observer.join()
    approved_observer.join()
    logger.info("Stopped.")


if __name__ == "__main__":
    main()
