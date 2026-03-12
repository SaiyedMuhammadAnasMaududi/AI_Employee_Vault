---
source_task: "EMAIL_test_silver.md"
created_at: "2026-02-24 14:00:00"
sensitive: true
business_post: true
status: pending
---

# Plan: EMAIL_test_silver.md

## Objective
Process urgent invoice request from client@example.com: send invoice to test@example.com
and draft a LinkedIn post announcing the new service launch.

## Steps
- [ ] Step 1: Read and confirm task details (email to test@example.com, LinkedIn post).
- [ ] Step 2: Create approval request for email send (new external contact — requires HITL).
- [ ] Step 3: Draft LinkedIn post and route to /Pending_Approval/ for human sign-off.
- [ ] Step 4: Wait for human to move approvals to /Approved/ or /Rejected/.
- [ ] Step 5: On approval — email_mcp executes send_email via Gmail API (dry-run).
- [ ] Step 6: Move EMAIL_test_silver.md to /Done/ when all actions resolved.
- [ ] Step 7: Append outcome to /Logs/agent_log.md.

## Approval Required
YES — two actions require human approval:
1. Email send to new external contact (test@example.com)
2. LinkedIn post about new service launch

## LinkedIn Post Draft
> ⚠️ DRAFT — Requires human approval before posting.

Excited to announce our new service launch! We're bringing cutting-edge solutions to help businesses work smarter.

Contact us today for exclusive early-access deals and a free consultation session.

Ready to transform your workflow? DM us or drop a comment below!

#NewService #Launch #BusinessGrowth #AI #Productivity

## Notes
- Source: Urgent invoice request from client@example.com (2026-02-24).
- Email body should include invoice attachment reference.
- LinkedIn post tone: professional with excitement.
