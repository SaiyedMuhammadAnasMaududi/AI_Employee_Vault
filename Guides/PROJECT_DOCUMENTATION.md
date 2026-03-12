# AI Employee Vault — Full Project Documentation

> **Project:** Personal AI Employee System
> **Owner:** Ai Employee (tafs4920@gmail.com)
> **Documented:** 2026-03-07
> **Status:** Gold Tier — Fully Operational

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Silver Tier — What We Built](#4-silver-tier--what-we-built)
5. [Gold Tier — What We Built](#5-gold-tier--what-we-built)
6. [Replacements & Why](#6-replacements--why)
7. [Errors We Faced & How We Fixed Them](#7-errors-we-faced--how-we-fixed-them)
8. [HITL Flow — Design & Implementation](#8-hitl-flow--design--implementation)
9. [Meta Social — The Long Road to Working](#9-meta-social--the-long-road-to-working)
10. [LinkedIn Auto-Post — Full Implementation](#10-linkedin-auto-post--full-implementation)
11. [Files & What Each Does](#11-files--what-each-does)
12. [What Is NOT Used & Why](#12-what-is-not-used--why)
13. [Business Configuration](#13-business-configuration)
14. [Lessons Learned](#14-lessons-learned)

---

## 1. Project Overview

The AI Employee Vault is a fully autonomous AI-powered business operations system running on a personal Windows 11 machine via WSL2. It acts as a virtual employee that:

- Reads and replies to emails automatically
- Monitors WhatsApp for important messages
- Posts daily content to LinkedIn, Facebook, and Instagram
- Creates and manages invoices in Odoo
- Generates weekly CEO briefings
- Monitors its own processes and self-heals on crashes

The system runs 24/7 via PM2, uses Playwright for browser automation, Meta Graph API for social media, Odoo XML-RPC for accounting, and Qwen CLI as the AI reasoning engine.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────┐
│                   INPUT CHANNELS                     │
│   Gmail Inbox   WhatsApp   LinkedIn   File Drops     │
└────────┬────────────┬──────────┬──────────┬─────────┘
         │            │          │          │
         ▼            ▼          ▼          ▼
┌─────────────────────────────────────────────────────┐
│                    WATCHERS                          │
│  gmail_watcher  whatsapp_watcher  linkedin_watcher  │
│            file_watcher                             │
│   (all create task files in /Needs_Action/)         │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              RALPH (Task Processor)                  │
│              ralph_wrapper.py                        │
│                                                     │
│  Classify task → Fast-path or Qwen reasoning        │
│  Check HITL threshold → Auto or Pending_Approval    │
└──────┬──────────────────┬───────────────────────────┘
       │                  │
       ▼                  ▼
  AUTO-EXECUTE      HUMAN APPROVAL
  immediately       /Pending_Approval/
       │                  │ (you move to /Approved/)
       │                  ▼
       │            Ralph re-reads → executes
       │
       ▼
┌─────────────────────────────────────────────────────┐
│                  MCP TOOLS                           │
│   email_mcp.py   odoo_mcp.py   meta_social_mcp.py   │
└─────────────────────────────────────────────────────┘
       │                │               │
       ▼                ▼               ▼
   Gmail SMTP       Odoo ERP      Facebook/Instagram
   (send email)   (invoices)     (Graph API posts)

┌─────────────────────────────────────────────────────┐
│              PROCESS MONITOR                         │
│              process_monitor.py                      │
│  Checks all PM2 processes every 5 min               │
│  Restarts crashed ones / ignores intentional stops  │
└─────────────────────────────────────────────────────┘
```

### Folder flow

```
/Needs_Action/      ← watchers write task files here
/Pending_Approval/  ← ralph pauses here for HITL
/Approved/          ← you move files here to approve
/Rejected/          ← you move files here to reject
/Done/              ← all completed tasks archived here
/Logs/              ← audit trail for every action
/Briefings/         ← CEO weekly briefings saved here
```

---

## 3. Tech Stack

| Component | Technology | Why |
|---|---|---|
| Runtime | Python 3 + Node.js | Python for AI/automation, Node for WhatsApp |
| Process manager | PM2 | Auto-restart, log management, startup on boot |
| Browser automation | Playwright (Chromium) | LinkedIn + WhatsApp need a real browser |
| AI reasoning | Qwen CLI | Free, local, no API key required |
| Email | Gmail IMAP + SMTP | Reliable, free, widely used |
| Social media | Meta Graph API v18 | Official API for Facebook + Instagram |
| Accounting | Odoo 19 (Docker) + XML-RPC | Full ERP, self-hosted, free |
| Environment | WSL2 on Windows 11 | Linux tools on Windows without dual boot |
| Secret management | python-dotenv (.env) | Simple, no external vault needed |
| File watching | watchdog (PollingObserver) | Works reliably in WSL2/NTFS mounts |

---

## 4. Silver Tier — What We Built

### gmail_watcher.py
- Polls Gmail inbox every 2 minutes via IMAP
- Detects new emails, skips newsletters and bots
- Creates task files in `/Needs_Action/` with full email content
- Tracks replied email IDs in `gmail_replied_ids.txt` to prevent duplicates
- Uses `gmail_last_uid.txt` to track last seen UID — restarts don't re-process old emails

### ralph_wrapper.py
- The central brain — polls `/Needs_Action/` every 10 seconds
- Classifies tasks: email, odoo, social, or general
- Runs fast-paths for structured tasks (no AI needed)
- Uses Qwen CLI for unstructured/general tasks
- Implements full HITL flow with `/Pending_Approval/` and `/Approved/` folders
- Generates CEO briefings every Sunday at 10 PM

### email_mcp.py
- MCP (Model Context Protocol) server for email operations
- Tools: `send_email`, `draft_email`
- Integrated with Gmail App Password via SMTP
- Respects `DRY_RUN=true` for testing without sending real emails
- All sends logged to `/Logs/agent_log.md`

### whatsapp_watcher.py
- Uses Playwright + Chromium to run WhatsApp Web
- Session saved after first QR scan — subsequent runs are automatic
- Watches for messages containing keywords: `urgent, invoice, approve, payment, asap, important`
- Creates Needs_Action files for matched messages
- Requires display (WSLg on Windows 11 or VcXsrv)

### linkedin_watcher.py (Silver features)
- Playwright-based LinkedIn session management
- Watches `/Approved/` for `action_type: linkedin_post` files
- Posts approved content to LinkedIn feed
- Monitors notifications for keyword matches

### file_watcher.py
- Watches the vault directory for new `.md` files dropped manually
- Routes them to ralph for processing
- Useful for manual task injection

### auth_setup.py
- Handles first-time OAuth and session setup
- `--gmail`: Gmail OAuth2 flow, saves token
- `--linkedin`: Opens browser for LinkedIn login, saves cookies
- `--whatsapp`: Opens browser for WhatsApp QR scan, saves session

---

## 5. Gold Tier — What We Built

### odoo_mcp.py
- Full Odoo ERP integration via XML-RPC
- Actions: `create_invoice`, `post_payment`, `get_balance`, `search_partner`
- HITL threshold: amounts > $50 go to `/Pending_Approval/`, under $50 auto-proceed
- `--force` flag bypasses HITL for already-approved actions (prevents re-loop)
- Dual audit logging: `/Logs/odoo_actions.md` + `/Logs/YYYY-MM-DD.json`

### meta_social_mcp.py
- Facebook and Instagram posting via Meta Graph API v18
- Actions: `post_facebook`, `post_instagram`, `generate_summary`
- Instagram: if no image URL provided, automatically uses `META_DEFAULT_IG_IMAGE`
- Retry decorator: 3 attempts with exponential backoff on API failures
- All posts logged to `/Logs/meta_social_actions.md`

### CEO Briefing (inside ralph_wrapper.py)
- Auto-runs every Sunday at 10 PM
- Pulls live Odoo data (outstanding balance, unpaid invoices)
- Reads email activity, social posts, LinkedIn history
- Compiles structured executive summary via Qwen
- Saves to `/Briefings/YYYY-MM-DD_ceo_briefing.md`
- No approval needed — read-only report

### process_monitor.py (formerly watchdog.py)
- Checks all PM2 processes every 5 minutes
- If a process is `errored` (crashed): restarts it automatically
- If a process is `stopped` (intentional): leaves it alone
- Logs all health checks to `/Logs/agent_log.md`

### LinkedIn Auto-Post (Gold additions to linkedin_watcher.py)
- Posts once per day at 9 AM (configurable)
- Topics rotate daily: AI & Automation, Productivity, Entrepreneurship, Tech & Innovation
- Content generated by Qwen CLI with structured prompt
- If Qwen fails: uses pre-written fallback posts (2 per topic, 8 total, rotated by week)
- After LinkedIn: auto cross-posts to Facebook AND Instagram
- Instagram always gets a topic-matched professional image
- Post history saved to `/Logs/linkedin_posts_history.md`
- Retry logic: if post fails, retries after 15 minutes (not stuck until next day)

---

## 6. Replacements & Why

### Claude CLI → Qwen CLI

**What:** The original design used `claude -p prompt --permission-mode bypassPermissions` for all AI reasoning in ralph and linkedin_watcher.

**Why replaced:** Claude CLI requires a valid `ANTHROPIC_API_KEY`. The key in `.env` was a placeholder (`your-anthropic-api-key-here`). Every general-task call was failing silently with "Invalid API key". We had two options: pay for Claude API access, or use Qwen which is free and runs locally.

**Decision:** User confirmed — use Qwen. System now runs 100% independently of Anthropic.

**New command in code:**
```python
# Old
["claude", "-p", prompt, "--permission-mode", "bypassPermissions"]

# New
["qwen", prompt, "--output-format", "text", "--approval-mode", "yolo"]
```

---

### watchdog.py → process_monitor.py

**What:** The process monitor script was originally named `watchdog.py`.

**Why renamed:** Python adds the current working directory to `sys.path`. Because `watchdog.py` existed in the vault directory, it shadowed the installed `watchdog` Python library package. Every script that did `from watchdog.observers.polling import PollingObserver` failed with:
```
ModuleNotFoundError: No module named 'watchdog.observers'; 'watchdog' is not a package
```

This broke `gmail_watcher.py`, `linkedin_watcher.py`, `file_watcher.py`, and `whatsapp_watcher.py` all at once.

**Fix:** Renamed `watchdog.py` → `process_monitor.py`, updated `ecosystem.config.js` to point to the new name, deleted the original. The `watchdog` library now imports correctly from `site-packages`.

---

### Direct Odoo/Social paths (bypassing AI loop)

**What:** Originally all tasks — even structured ones like "create invoice for X for $Y" — went through the full Qwen reasoning loop.

**Why changed:** Structured tasks (Odoo invoices, social posts) don't need AI reasoning. They have a fixed format with frontmatter fields. Sending them through Qwen was slow, unreliable, and wasted the general reasoning capacity for tasks that actually need it.

**What was added to ralph:**
- `_is_odoo_task()` — detects `action_type: odoo_create_invoice` etc.
- `_is_social_task()` — detects `action_type: meta_post`
- `_run_odoo_fast_path()` — parses frontmatter, checks HITL, calls odoo_mcp.py directly
- `_run_social_fast_path()` — always creates Pending_Approval (Meta always requires HITL)

---

### Default Instagram image (no longer requires explicit image URL)

**What:** Instagram posting originally required `--image-url` to be passed explicitly. Without it, the code raised `ValueError("Instagram requires an image_url")`.

**Why changed:** When ralph or linkedin_watcher cross-posts automatically, they don't have a user-provided image. Raising an error meant Instagram was always skipped in automated flows.

**Fix:** Added `META_DEFAULT_IG_IMAGE` config variable. If no image URL is provided, the default is used silently. Also mapped each LinkedIn topic to a specific curated professional Unsplash image so cross-posts always have relevant visuals.

---

## 7. Errors We Faced & How We Fixed Them

---

### Error 1 — Watchdog restarting intentionally stopped processes

**Symptom:** User ran `pm2 stop whatsapp`. The watchdog restarted it within 5 minutes. Same for any process that was deliberately stopped.

**Root cause:** `process_monitor.py` treated `stopped` status the same as `errored` — both triggered `restart_process()`.

**Fix:** Added explicit branch in the health check loop:
```python
if status == "online":
    failure_counts[name] = 0       # healthy, reset counter
elif status == "stopped":
    failure_counts[name] = 0       # intentional — do nothing
    logger.info(f"{name}: stopped (intentional — skipping)")
else:                               # errored, unknown = crash
    failure_counts[name] += 1
    restart_process(name)
```

---

### Error 2 — ModuleNotFoundError: watchdog is not a package

**Symptom:**
```
ModuleNotFoundError: No module named 'watchdog.observers'; 'watchdog' is not a package
```
Appeared in gmail_watcher, linkedin_watcher, file_watcher, whatsapp_watcher all at once after watchdog.py was created.

**Root cause:** Python inserts the script's directory into `sys.path[0]`. A file named `watchdog.py` in that directory shadows the installed `watchdog` library. When `from watchdog.observers.polling import PollingObserver` was called, Python found our local `watchdog.py` instead of the real package — and a `.py` file has no `.observers` submodule.

**Fix:** Renamed `watchdog.py` → `process_monitor.py`. Updated `ecosystem.config.js`. Deleted original. Problem gone permanently.

---

### Error 3 — Odoo authentication returning uid=False

**Symptom:**
```python
uid = models.execute_kw('res.users', 'authenticate', ...)
# uid = False
```
All Odoo operations failed silently. No invoice could be created.

**Root cause:** `.env` had `ODOO_USER=admin`. The actual Odoo database login is an email address, not `admin`. Found by querying the database directly:
```bash
docker exec odoo19-db-1 bash -c "psql -U odoo -d ai_employee_db -c \"SELECT login FROM res_users;\""
# Result: tafs4920@gmail.com
```

**Fix:** Updated `.env`:
```
ODOO_USER=tafs4920@gmail.com
```

---

### Error 4 — HITL Re-Loop (approved invoice creating new pending approval)

**Symptom:** User approved an Odoo invoice in `/Approved/`. Ralph picked it up, called `odoo_mcp.py` to execute — but `odoo_mcp.py` saw the amount was > $50, triggered HITL again, and created a NEW file in `/Pending_Approval/`. Infinite loop.

**Root cause:** When ralph executed an already-approved action, it called `odoo_mcp.py` without any flag to indicate "this was already approved by a human". The HITL check in `odoo_mcp.py` ran again on the same amount.

**Fix:** Added `--force` flag to `odoo_mcp.py`:
```python
# In OdooMCP.__init__
self.force = force  # skip HITL — action already approved by human

# In create_invoice / post_payment
if amount > HITL_LIMIT and not self.force:
    _hitl_pending(...)   # only trigger if NOT forced
```

Ralph passes `--force` when executing from `/Approved/`:
```python
cmd = ["python3", "odoo_mcp.py", "--action", "create_invoice", ..., "--force"]
```

---

### Error 5 — Meta Graph API 403 Forbidden (multiple causes)

This was the most complex error, with three separate root causes discovered one by one.

**Symptom:** Every attempt to post to Facebook returned:
```
HTTP Error 403: Forbidden
```

**Root cause 1 — Wrong page ID**
The user provided page ID `1032200303307355` initially. When we called `/me` with the token, it returned `{"name": "Ai Employee", "id": "122103268755288659"}`. We had `META_PAGE_ID=122103268755288659` (the user's profile ID, not the page). The actual page "Ai Generation" was `1032200303307355`.

**Root cause 2 — App in Development mode**
Facebook apps in Development mode can only be used by the app's admin/developer accounts. The user switched the app to Live mode.

**Root cause 3 — User token, not Page Access Token, and wrong account**
Even after switching to Live mode, the token belonged to "Ai Employee" (user ID: `122103268755288659`) who had NO pages in `me/accounts` (returned empty). This meant the token holder didn't admin any Facebook page.

**Discovery process:**
```python
# debug_token revealed:
{
  "type": "USER",           # User token, not Page token
  "granular_scopes": [
    {"scope": "pages_manage_posts", "target_ids": ["1032200303307355", "1036269206231768"]}
  ]
}
# But me/accounts returned: {"data": []}
# Meaning: user has permissions scoped to those pages but isn't their admin
```

**Fix:** Retrieved Page Access Token directly via the API:
```python
GET /1036269206231768?fields=id,name,access_token
# Returns the page's own access_token
```

Used the Page Access Token (not User token) for all posts. Switched target to "My Services" page (`1036269206231768`) which was properly connected to the user's app with admin access.

---

### Error 6 — Instagram requiring image URL (breaking automated cross-posts)

**Symptom:** When LinkedIn auto-post triggered Facebook+Instagram cross-posting, Instagram always failed:
```
ValueError: Instagram requires an image_url
```

**Root cause:** Instagram Graph API does not allow text-only feed posts. The cross-post function had no image to provide.

**Fix (two-part):**
1. Added `TOPIC_IMAGE_URLS` mapping in `linkedin_watcher.py` — each topic maps to a curated Unsplash professional photo
2. Added `META_DEFAULT_IG_IMAGE` fallback in `meta_social_mcp.py` — if no image provided, default image is used silently

```python
TOPIC_IMAGE_URLS = {
    "AI & Automation":  "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=1080&q=80",
    "Productivity":     "https://images.unsplash.com/photo-1484480974693-6ca0a78fb36b?w=1080&q=80",
    "Entrepreneurship": "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=1080&q=80",
    "Tech & Innovation":"https://images.unsplash.com/photo-1518770660439-4636190af475?w=1080&q=80",
}
```

---

### Error 7 — PM2 processes all going offline after restart command

**Symptom:** After running `pm2 restart` with wrong process names, all 6 processes went to `stopped` state.

**Fix:** `pm2 resurrect` restored all processes from the last saved state. Always run `pm2 save` after any configuration changes so `resurrect` has a fresh snapshot.

---

## 8. HITL Flow — Design & Implementation

HITL (Human-in-the-Loop) is the safety layer that prevents the AI from taking high-stakes actions autonomously.

### Rules (from Company_Handbook.md)

| Action | Threshold | Behaviour |
|---|---|---|
| Email to known contact, low value | Always | Auto-send |
| Email to new/unknown contact | Any | HITL |
| Odoo invoice | > $50 | HITL |
| Odoo invoice | ≤ $50 | Auto |
| Odoo payment | Any | HITL |
| Meta post (FB/IG via ralph) | Always | HITL |
| LinkedIn auto-post (scheduled) | — | Auto (trusted) |
| CEO Briefing | — | Auto (read-only) |

### File format for Pending_Approval

```yaml
---
action_type: odoo_create_invoice
partner: ClientName
description: Service description
amount: 500
reason: Amount $500 exceeds HITL threshold of $50
---
Invoice request for ClientName — $500
```

### Implementation

- Ralph checks task type and amount before acting
- If HITL required: writes frontmatter file to `/Pending_Approval/`, stops
- File watcher detects when user moves file to `/Approved/`
- Ralph reads it, calls the appropriate MCP tool with `--force` to skip re-check
- On completion: moves file to `/Done/`, logs action

---

## 9. Meta Social — The Long Road to Working

### Timeline of what we tried

| Attempt | Token | Page ID | Result |
|---|---|---|---|
| 1 | User token (Ai Employee) | `122103268755288659` | 403 — wrong ID (profile, not page) |
| 2 | User token | `1032200303307355` | 403 — app in Development mode |
| 3 | New token after Live mode | `122103268755288659` | 403 — still wrong page |
| 4 | New token | `1032200303307355` | 403 — user not page admin |
| 5 | Page Access Token via API | `1036269206231768` | ✓ SUCCESS |

### Key learning

Facebook's `me/accounts` only returns pages where the **token holder** is a legitimate page admin. Having `pages_manage_posts` permission in the token's scopes does NOT mean you can post — the underlying Facebook account must also have admin role on that page in Facebook's system.

The fix was fetching the Page Access Token directly:
```
GET /{page_id}?fields=access_token&access_token={user_token}
```
This returns a token that acts AS the page, bypassing the user-level admin check.

### Final configuration

- **Facebook Page:** My Services (`1036269206231768`)
- **Instagram:** Connected Business Account (`17841446757453241`)
- **Token type:** Page Access Token (not User token)
- **Permissions:** `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`
- **Token expiry:** ~60 days — must be refreshed via Graph API Explorer

---

## 10. LinkedIn Auto-Post — Full Implementation

### Architecture

```
9:00 AM daily
     │
     ▼
get_todays_topic()         → cycles: AI/Productivity/Entrepreneurship/Tech
     │
     ▼
generate_linkedin_post()   → calls Qwen CLI with structured prompt
     │
     ├─ Qwen success → use generated content
     └─ Qwen fails   → get_fallback_post() → pre-written post (rotated by week)
     │
     ▼
post_to_linkedin()         → Playwright posts to LinkedIn feed
     │
     ├─ Success → mark_posted_today() + save_post_history() + cross_post_to_meta()
     └─ Failure → schedule_retry(15 min) → retry on next poll cycle
     │
     ▼
cross_post_to_meta(content, topic)
     ├─ post_facebook → My Services page
     └─ post_instagram → with topic-matched image URL
```

### Fallback system

8 pre-written posts (2 per topic) ensure posting continues even if:
- Qwen CLI is unavailable
- Qwen times out (>120s)
- Network is unavailable for Qwen
- Qwen returns empty output

Fallback selection rotates by ISO week number so different posts appear each week.

### State files

| File | Purpose |
|---|---|
| `linkedin_last_post_date.txt` | Stores date of last successful post (YYYY-MM-DD) |
| `linkedin_retry_time.txt` | Unix timestamp for next retry after failure |
| `Logs/linkedin_posts_history.md` | Full archive of every post with timestamp + source |

---

## 11. Files & What Each Does

### Core scripts

| File | Role |
|---|---|
| `ralph_wrapper.py` | Central task processor, HITL logic, CEO briefing, Qwen integration |
| `gmail_watcher.py` | Gmail IMAP polling, email-to-task conversion |
| `linkedin_watcher.py` | LinkedIn Playwright session, daily auto-post, notification monitor |
| `whatsapp_watcher.py` | WhatsApp Web Playwright, keyword detection |
| `file_watcher.py` | Vault directory monitor, manual task injection |
| `process_monitor.py` | PM2 health monitor, auto-restart on crash |
| `email_mcp.py` | Gmail SMTP MCP server (send/draft email) |
| `odoo_mcp.py` | Odoo XML-RPC MCP server (invoices, payments, balance) |
| `meta_social_mcp.py` | Meta Graph API MCP server (FB + IG posts) |
| `auth_setup.py` | First-time OAuth and session setup for Gmail/LinkedIn/WhatsApp |

### Config files

| File | Role |
|---|---|
| `.env` | All credentials and configuration |
| `.mcp.json` | MCP server definitions for Claude Code integration |
| `ecosystem.config.js` | PM2 process definitions |
| `package.json` | Node.js dependencies (for WhatsApp bot) |

### State files (auto-generated, do not delete)

| File | Role |
|---|---|
| `gmail_last_uid.txt` | Last Gmail UID processed (prevents re-processing) |
| `gmail_replied_ids.txt` | All replied message IDs (prevents duplicate replies) |
| `linkedin_last_post_date.txt` | Date of last LinkedIn auto-post |
| `linkedin_cookies.json` | LinkedIn Playwright session cookies |
| `gmail_token.json` | Gmail OAuth2 token (auto-refreshed) |

### Log files (root level — generated by PM2)

| File | Role |
|---|---|
| `ralph_wrapper.log` | Ralph processing log |
| `gmail_watcher.log` | Gmail detection log |
| `linkedin_watcher.log` | LinkedIn activity log |
| `whatsapp_watcher.log` | WhatsApp activity log |
| `meta_social_mcp.log` | Social posting log |
| `odoo_mcp.log` | Odoo action log |
| `email_mcp.log` | Email send log |
| `file_watcher.log` | File watch log |

---

## 12. What Is NOT Used & Why

| Item | Why removed / not used |
|---|---|
| **Claude CLI** | Replaced by Qwen CLI — no Anthropic API key required |
| **`ANTHROPIC_API_KEY`** | Still in `.env` as placeholder but never called |
| **`watchdog.py`** | Renamed to `process_monitor.py` — filename caused Python library shadowing |
| **`run_watchers.sh`** | Replaced by PM2 — manual shell script no longer needed |
| **`base_watcher.py`** | Created early in project, never imported by any script |
| **`Untitled.base`** | Editor artifact, unknown origin, deleted |
| **`linkedin_error.png`** | Debug screenshot generated during LinkedIn testing, deleted |
| **`whatsapp_debug.png`** | Debug screenshot generated during WhatsApp testing, deleted |
| **`watchdog.log`** | Leftover log from before rename, deleted |
| **`STARTUP_GUIDE.md`** | Superseded by `OPERATIONS_GUIDE.md` and `QUICK_REFERENCE.md` |
| **`linkedin_watcher_guide.md`** | Superseded by `QUICK_REFERENCE.md` |
| **`META_DRY_RUN=true`** | Was true during development, now false — live posting active |
| **`ODOO_DRY_RUN=true`** | Was true during development, now false — live Odoo active |
| **`DRY_RUN=true`** | Was true during testing, now false — real emails being sent |

---

## 13. Business Configuration

### Services offered

| Service | Price |
|---|---|
| AI Automation Consulting | $150/hr |
| Business Process Automation | $500/project |
| Social Media Management | $200/month |
| Email Management | $100/month |

### Accounts & integrations

| Platform | Account | ID |
|---|---|---|
| Gmail | tafs4920@gmail.com | — |
| Facebook Page | My Services | 1036269206231768 |
| Instagram | Connected Business Account | 17841446757453241 |
| Odoo | tafs4920@gmail.com | localhost:8069 / ai_employee_db |
| Meta App | Ai app | 1439463710980858 |
| LinkedIn | Ai Employee profile | — |

### Approval thresholds

| Action | Auto | HITL |
|---|---|---|
| Odoo invoice / payment | ≤ $50 | > $50 |
| Email reply | Known contact | New contact |
| Social post (FB/IG via ralph) | Never | Always |
| LinkedIn daily auto-post | Always | Never |
| CEO Briefing | Always | Never |

---

## 14. Lessons Learned

1. **File naming matters.** A Python script sharing a name with a pip package silently breaks all imports of that package across the entire project. Always check `pip list` before naming a new script.

2. **Facebook token types are not interchangeable.** A User Access Token and a Page Access Token look identical but behave completely differently. Always use Page Access Token for page operations. Always verify with `debug_token` endpoint.

3. **`me/accounts` is the truth.** If a Facebook page doesn't appear in `me/accounts`, the token holder cannot post to it — regardless of what permissions the token claims to have. This is the definitive check.

4. **HITL loops must be broken explicitly.** Any system where "approve → execute" can trigger another "needs approval" will loop infinitely. The `--force` flag pattern (skip re-check when action already approved) is the clean solution.

5. **PM2 `stopped` vs `errored` are semantically different.** A watchdog that restarts stopped processes defeats the purpose of being able to stop processes. Always check status before deciding to restart.

6. **Instagram requires images — design for this upfront.** Text-only Instagram posts are not supported by the Graph API. Any automated posting system targeting Instagram must always have an image strategy, not treat images as optional.

7. **Fallback content prevents silent failures.** If your AI content generator fails at 9 AM, you either miss the post or have a fallback. Pre-written fallback posts ensure the business keeps appearing active even during AI failures.

8. **Docker Odoo + WSL2 works reliably.** XML-RPC over localhost is fast and stable. The only gotcha is that Odoo uses email addresses as login, not usernames.

9. **`pm2 save` must be run after every change.** `pm2 resurrect` restores the last saved state. If you change process configurations and don't save, a reboot loses all changes.

10. **Dry-run mode is essential during development.** All three MCP tools (`email_mcp`, `odoo_mcp`, `meta_social_mcp`) support dry-run mode. Always start with dry-run, verify logs, then go live. Never test on production without a dry-run path.

---

*Documentation covers the full Silver Tier + Gold Tier implementation. System is fully operational as of 2026-03-07.*
