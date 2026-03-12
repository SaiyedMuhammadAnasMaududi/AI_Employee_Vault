# AI Employee — Quick Reference

---

## START EVERYTHING

```bash
pm2 resurrect
```

```bash
pm2 list          # confirm all processes online
```

---

## START / STOP INDIVIDUAL WATCHERS

```bash
pm2 start gmail
pm2 start ralph
pm2 start linkedin
pm2 start whatsapp
pm2 start watchdog

pm2 stop gmail
pm2 stop linkedin
pm2 stop whatsapp

pm2 restart ralph    # after any config change
pm2 restart all
```

---

## LIVE LOGS — WATCH IN REAL TIME

```bash
pm2 logs ralph          # task processing + email replies
pm2 logs gmail          # new emails detected
pm2 logs linkedin       # auto-post + notifications
pm2 logs whatsapp       # keyword messages detected
pm2 logs watchdog       # process health monitor
pm2 logs               # everything together
```

> Press `Ctrl+C` to stop watching — does NOT stop the processes.

---

## APPROVAL FLOW COMMANDS

```bash
ls Pending_Approval/                          # see what's waiting
cat Pending_Approval/<filename>.md            # read it

mv Pending_Approval/<filename>.md Approved/   # approve
mv Pending_Approval/<filename>.md Rejected/   # reject
```

---

## CHECK WHAT HAPPENED (AUDIT LOGS)

```bash
tail -30 Logs/agent_log.md                   # all actions
tail -30 Logs/odoo_actions.md                # invoices & payments
tail -30 Logs/meta_social_actions.md         # FB + IG posts
tail -30 Logs/linkedin_posts_history.md      # LinkedIn auto-posts
```

---

## TEST EACH FEATURE MANUALLY

```bash
# Gmail — check inbox now
python3 gmail_watcher.py --once

# Odoo — check balance
python3 odoo_mcp.py --action get_balance

# Facebook — test post
python3 meta_social_mcp.py --action post_facebook --message "Test post"

# Instagram — test post (image auto-used if none given)
python3 meta_social_mcp.py --action post_instagram --message "Test post"

# LinkedIn — post right now
python3 linkedin_watcher.py --post --content "Test post #AI"

# CEO Briefing — generate now
python3 -c "from ralph_wrapper import generate_ceo_briefing; generate_ceo_briefing()"
```

---

## ARCHITECTURE — HOW EACH SCENARIO WORKS

---

### SCENARIO 1 — Email Received (known contact, low value)

```
Gmail inbox
  └─► gmail_watcher.py        polls every 2 min
        └─► /Needs_Action/email_*.md   task file created
              └─► ralph_wrapper.py     picks up within 10s
                    └─► Qwen CLI       drafts reply
                          └─► email_mcp.py   sends via Gmail SMTP
                                └─► /Done/   task archived
```

**Watch it live:**
```bash
pm2 logs gmail    # "New email from ..."
pm2 logs ralph    # "Drafting reply..." → "Sent"
```

---

### SCENARIO 2 — Email Received (new contact or sensitive)

```
Gmail inbox
  └─► gmail_watcher.py
        └─► /Needs_Action/email_*.md
              └─► ralph_wrapper.py
                    └─► /Pending_Approval/hitl_email_*.md   ← PAUSED
                                ▼
                    YOU move file to /Approved/
                                ▼
                    ralph_wrapper.py   resumes
                          └─► email_mcp.py   sends
                                └─► /Done/
```

**Commands:**
```bash
pm2 logs ralph
ls Pending_Approval/
mv Pending_Approval/<file>.md Approved/
```

---

### SCENARIO 3 — WhatsApp Keyword Message

```
WhatsApp message arrives
  └─► whatsapp_watcher.py      detects keyword (urgent/invoice/payment...)
        └─► /Needs_Action/action_whatsapp_*.md   created
              └─► ralph_wrapper.py   reads and decides action
                    └─► email_mcp.py / Qwen   responds if needed
                          └─► /Done/
```

**Watch it live:**
```bash
pm2 logs whatsapp    # "Keyword match: invoice — saving action file"
ls Needs_Action/     # file appears
pm2 logs ralph       # processing
```

---

### SCENARIO 4 — LinkedIn Daily Auto-Post (9 AM)

```
9:00 AM — linkedin_watcher.py triggers
  └─► Qwen CLI         generates 150-250 word post on today's topic
  │     (fallback: pre-written post if Qwen fails)
  └─► Playwright       posts to LinkedIn feed
        └─► meta_social_mcp.py
              ├─► Facebook page (My Services)    post published
              └─► Instagram account              post published
                    (topic-matched image auto-attached)
  └─► /Logs/linkedin_posts_history.md    post saved
```

**Topic rotation:**
```
Day 1 → AI & Automation
Day 2 → Productivity
Day 3 → Entrepreneurship
Day 4 → Tech & Innovation
Day 5 → AI & Automation  (repeats)
```

**Watch it live:**
```bash
pm2 logs linkedin                          # "Auto-post: generating..."
tail -5 linkedin_last_post_date.txt        # last post date
tail -20 Logs/linkedin_posts_history.md   # content posted
tail -20 Logs/meta_social_actions.md      # FB + IG confirmation
```

---

### SCENARIO 5 — Odoo Invoice (under $50, auto-proceeds)

```
/Needs_Action/invoice.md   dropped (amount ≤ $50)
  └─► ralph_wrapper.py     detects odoo_invoice type
        └─► odoo_mcp.py    creates invoice directly in Odoo
              └─► /Done/   archived
```

**Watch it live:**
```bash
pm2 logs ralph
tail -10 Logs/odoo_actions.md
python3 odoo_mcp.py --action get_balance
```

---

### SCENARIO 6 — Odoo Invoice (over $50, requires approval)

```
/Needs_Action/invoice.md   dropped (amount > $50)
  └─► ralph_wrapper.py
        └─► /Pending_Approval/hitl_pending_*.md   ← PAUSED
                      ▼
          YOU move to /Approved/
                      ▼
          ralph_wrapper.py   resumes
                └─► odoo_mcp.py --force   creates invoice (bypasses re-check)
                      └─► /Done/
```

**Commands:**
```bash
ls Pending_Approval/
cat Pending_Approval/hitl_pending_*.md
mv Pending_Approval/hitl_pending_*.md Approved/
tail -5 Logs/odoo_actions.md
```

---

### SCENARIO 7 — CEO Weekly Briefing (Sunday 10 PM, automatic)

```
Sunday 10 PM — ralph_wrapper.py internal scheduler triggers
  └─► Odoo MCP          pulls: outstanding invoices, balance
  └─► Logs/             reads: emails, social posts, LinkedIn history
  └─► Qwen CLI          compiles executive summary
        └─► /Briefings/YYYY-MM-DD_ceo_briefing.md   saved
```

**Check it:**
```bash
ls -t Briefings/ | head -3
cat Briefings/$(ls -t Briefings/ | head -1)
```

---

### SCENARIO 8 — Process Crashes (Watchdog recovery)

```
Any process crashes (status: errored)
  └─► process_monitor.py   detects within 5 min
        └─► pm2 restart <name>   automatic recovery
              └─► Logs/agent_log.md   restart logged

Intentionally stopped (pm2 stop <name>)
  └─► process_monitor.py   sees status: stopped → does nothing
```

**Watch it:**
```bash
pm2 logs watchdog    # "ralph: online ✓" or "ralph: errored — restarting"
```

---

## APPROVAL THRESHOLDS (COMPANY RULES)

| Action | Auto or HITL |
|---|---|
| Email to known contact | Auto |
| Email to new/unknown contact | HITL |
| Odoo invoice ≤ $50 | Auto |
| Odoo invoice > $50 | HITL |
| Odoo payment (any) | HITL |
| Facebook post | HITL (via ralph) |
| Instagram post | HITL (via ralph) |
| LinkedIn post (auto-post) | Auto (scheduled) |
| CEO Briefing | Auto (read-only) |
