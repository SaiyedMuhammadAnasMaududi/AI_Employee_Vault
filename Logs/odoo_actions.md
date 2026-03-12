
## 2026-03-01 16:39:53 — get_balance
- **Params:** {}
- **Result:** dry-run
- **Detail:** {'status': 'dry-run', 'outstanding_receivables': 0.0, 'unpaid_invoices': 0, 'currency': 'USD'}

## 2026-03-01 16:41:27 — create_invoice
- **Params:** {"partner": "Test Client", "amount": 30.0, "description": "Consulting"}
- **Result:** dry-run
- **Detail:** {'status': 'dry-run', 'invoice_id': 0, 'partner': 'Test Client', 'amount': 30.0, 'description': 'Consulting'}

## 2026-03-01 16:41:29 — create_invoice
- **Params:** {"partner": "Test Client", "amount": 150.0, "description": "Big Project"}
- **Result:** hitl_pending
- **Detail:** amount $150.0 > limit

## 2026-03-01 17:00:27 — create_invoice
- **Params:** {"partner": "Test Client", "amount": 150.0, "description": "Gold Tier Validation Test"}
- **Result:** hitl_pending
- **Detail:** amount $150.0 > limit

## 2026-03-01 17:11:48 — create_invoice
- **Params:** {"partner": "Test Client", "amount": 30.0, "description": "Small Task"}
- **Result:** dry-run
- **Detail:** {'status': 'dry-run', 'invoice_id': 0, 'partner': 'Test Client', 'amount': 30.0, 'description': 'Small Task'}

## 2026-03-01 17:14:11 — get_balance
- **Params:** {}
- **Result:** dry-run
- **Detail:** {'status': 'dry-run', 'outstanding_receivables': 0.0, 'unpaid_invoices': 0, 'currency': 'USD'}

## 2026-03-02 01:22:45 — create_invoice
- **Params:** {"partner": "Test Client", "amount": 150.0, "description": "Big Project"}
- **Result:** hitl_pending
- **Detail:** amount $150.0 > limit

## 2026-03-02 01:22:45 — create_invoice
- **Params:** {"partner": "Test Client", "amount": 150.0, "description": "Gold Tier Validation Test"}
- **Result:** hitl_pending
- **Detail:** amount $150.0 > limit

## 2026-03-02 01:24:18 — search_partner
- **Params:** {"name": "Test"}
- **Result:** error
- **Detail:** Odoo auth failed — check ODOO_USER (admin) and ODOO_API_KEY

## 2026-03-02 01:26:32 — search_partner
- **Params:** {"name": "Test"}
- **Result:** error
- **Detail:** Odoo auth failed — check ODOO_USER (admin) and ODOO_API_KEY

## 2026-03-02 01:32:04 — search_partner
- **Params:** {"name": "Test"}
- **Result:** success
- **Detail:** 1 found

## 2026-03-02 02:36:08 — create_invoice
- **Params:** {"partner": "Test Client", "amount": 150.0, "description": "Gold Tier Validation Test"}
- **Result:** hitl_pending
- **Detail:** amount $150.0 > limit

## 2026-03-02 02:36:10 — create_invoice
- **Params:** {"partner": "Test Client", "amount": 150.0, "description": "Big Project"}
- **Result:** hitl_pending
- **Detail:** amount $150.0 > limit

## 2026-03-02 02:38:37 — create_invoice
- **Params:** {"partner": "Test Client", "amount": 150.0, "description": "Gold Tier Validation Test"}
- **Result:** error
- **Detail:** Partner not found: Test Client

## 2026-03-02 02:38:39 — create_invoice
- **Params:** {"partner": "Test Client", "amount": 150.0, "description": "Big Project"}
- **Result:** error
- **Detail:** Partner not found: Test Client

## 2026-03-02 02:39:32 — search_partner
- **Params:** {"name": "test"}
- **Result:** success
- **Detail:** 1 found

## 2026-03-02 02:39:46 — create_invoice
- **Params:** {"partner": "testclient", "amount": 150.0, "description": "Gold Tier Validation Test"}
- **Result:** success
- **Detail:** invoice_id=3

## 2026-03-02 02:54:27 — create_invoice
- **Params:** {"partner": "testclient", "amount": 1500.0, "description": "Service Fee - Gold Tier Validation"}
- **Result:** success
- **Detail:** invoice_id=4

## 2026-03-02 02:56:12 — get_balance
- **Params:** {}
- **Result:** success
- **Detail:** {'status': 'success', 'outstanding_receivables': 5719.5, 'unpaid_invoices': 4, 'currency': 'USD'}

## 2026-03-07 05:36:42 — get_balance
- **Params:** {}
- **Result:** success
- **Detail:** {'status': 'success', 'outstanding_receivables': 5719.5, 'unpaid_invoices': 4, 'currency': 'USD'}
