---
action_type: "send_email"
to: "test@example.com"
subject: "Invoice Request — Urgent"
body: "Dear Client,\n\nPlease find attached your requested invoice. Let us know if you have any questions.\n\nBest regards,\nAI Employee"
reason: "Sending invoice to new external contact — requires approval per Company Handbook"
sensitive: "true"
created_at: "2026-02-24 14:00:00"
status: "pending"
---

# Approval Required: Send Email

## Action Details
- **Type:** send_email
- **To:** test@example.com
- **Subject:** Invoice Request — Urgent
- **Reason:** Sending invoice to new external contact — requires approval per Company Handbook

## Email Body
Dear Client,

Please find attached your requested invoice. Let us know if you have any questions.

Best regards,
AI Employee

## To Approve
Move this file to /Approved/ folder.

## To Reject
Move this file to /Rejected/ folder.
