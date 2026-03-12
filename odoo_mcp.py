#!/usr/bin/env python3
"""
odoo_mcp.py - Gold Tier Odoo Accounting MCP
=============================================
Provides accounting operations via Odoo JSON-RPC.

Commands:
  create_invoice  --partner NAME --amount FLOAT --description TEXT [--dry-run]
  post_payment    --invoice-id INT --amount FLOAT [--dry-run]
  get_balance     [--dry-run]
  search_partner  --name NAME [--dry-run]

HITL: amounts > $50 create a Pending_Approval file instead of acting.
Audit: every action logged to /Logs/odoo_actions.md + /Logs/YYYY-MM-DD.json
"""

import os
import sys
import json
import time
import logging
import argparse
import functools
import xmlrpc.client
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
except ImportError:
    print("Error: python-dotenv not found. Run: pip install python-dotenv")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VAULT_DIR   = Path(__file__).parent
LOGS_DIR    = VAULT_DIR / "Logs"
ODOO_LOG    = LOGS_DIR / "odoo_actions.md"
PENDING_DIR = VAULT_DIR / "Pending_Approval"

load_dotenv(VAULT_DIR / ".env")

ODOO_URL     = os.getenv("ODOO_URL", "http://localhost:8069")
ODOO_DB      = os.getenv("ODOO_DB", "ai_employee_db")
ODOO_USER    = os.getenv("ODOO_USER", "admin")
ODOO_API_KEY = os.getenv("ODOO_API_KEY", "")
HITL_LIMIT   = float(os.getenv("ODOO_HITL_LIMIT", "50"))  # require approval above this

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(VAULT_DIR / "odoo_mcp.log"),
    ],
)
logger = logging.getLogger("odoo_mcp")


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def with_retry(retries: int = 3, delay: float = 2.0):
    """Retry a function up to `retries` times with exponential backoff."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, retries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < retries:
                        wait = delay * (2 ** (attempt - 1))
                        logger.warning(f"[retry {attempt}/{retries}] {fn.__name__} failed: {e} — retrying in {wait:.0f}s")
                        time.sleep(wait)
            logger.error(f"{fn.__name__} failed after {retries} retries: {last_exc}")
            raise last_exc
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------

def _audit_log(action: str, params: dict, result: str, detail: str = "") -> None:
    """Write to both odoo_actions.md and today's JSON log."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Markdown log
    with open(ODOO_LOG, "a", encoding="utf-8") as f:
        f.write(f"\n## {ts} — {action}\n")
        f.write(f"- **Params:** {json.dumps(params)}\n")
        f.write(f"- **Result:** {result}\n")
        if detail:
            f.write(f"- **Detail:** {detail}\n")

    # Daily JSON log
    today      = datetime.now().strftime("%Y-%m-%d")
    json_log   = LOGS_DIR / f"{today}.json"
    entry      = {"timestamp": ts, "actor": "odoo_mcp", "action": action,
                  "params": params, "result": result, "detail": detail}
    records    = []
    if json_log.exists():
        try:
            records = json.loads(json_log.read_text(encoding="utf-8"))
        except Exception:
            records = []
    records.append(entry)
    json_log.write_text(json.dumps(records, indent=2), encoding="utf-8")


def _hitl_pending(action: str, params: dict, reason: str) -> None:
    """Create a Pending_Approval file for human review."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    epoch    = int(time.time())
    filename = f"approval_odoo_{action}_{epoch}.md"
    content  = f"""---
action_type: "odoo_{action}"
reason: "{reason}"
sensitive: "true"
created_at: "{ts}"
status: "pending"
params: '{json.dumps(params)}'
---

# Odoo Action Requires Approval

**Action:** {action}
**Reason:** {reason}
**Params:** {json.dumps(params, indent=2)}

Move to /Approved/ to execute, or /Rejected/ to cancel.
"""
    (PENDING_DIR / filename).write_text(content, encoding="utf-8")
    logger.info(f"[HITL] Created Pending_Approval: {filename}")
    print(f"HITL_PENDING:{filename}")


# ---------------------------------------------------------------------------
# Odoo client
# ---------------------------------------------------------------------------

class OdooMCP:
    """Thin wrapper around Odoo XML-RPC with retry and audit logging."""

    def __init__(self, dry_run: bool = False, force: bool = False):
        self.dry_run = dry_run or os.getenv("ODOO_DRY_RUN", "false").lower() == "true"
        self.force   = force   # skip HITL threshold — action already approved by human
        self._uid    = None

    @with_retry(retries=3, delay=2.0)
    def _authenticate(self) -> int:
        if self._uid:
            return self._uid
        common   = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
        uid      = common.authenticate(ODOO_DB, ODOO_USER, ODOO_API_KEY, {})
        if not uid:
            raise RuntimeError(f"Odoo auth failed — check ODOO_USER ({ODOO_USER}) and ODOO_API_KEY")
        self._uid = uid
        logger.info(f"Odoo authenticated (uid={uid})")
        return uid

    def _models(self):
        return xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

    @with_retry(retries=3, delay=2.0)
    def _call(self, model: str, method: str, args: list, kwargs: dict = None):
        uid = self._authenticate()
        return self._models().execute_kw(
            ODOO_DB, uid, ODOO_API_KEY, model, method, args, kwargs or {}
        )

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    def search_partner(self, name: str) -> list:
        """Find partners matching name. Returns list of {id, name, email}."""
        params = {"name": name}
        logger.info(f"search_partner: '{name}'")

        if self.dry_run:
            result = [{"id": 999, "name": f"{name} (dry-run)", "email": "dry@run.local"}]
            _audit_log("search_partner", params, "dry-run", str(result))
            print(json.dumps(result))
            return result

        try:
            ids = self._call("res.partner", "search", [[["name", "ilike", name]]])
            partners = self._call("res.partner", "read", [ids], {"fields": ["id", "name", "email"]})
            _audit_log("search_partner", params, "success", f"{len(partners)} found")
            print(json.dumps(partners))
            return partners
        except Exception as e:
            _audit_log("search_partner", params, "error", str(e))
            logger.error(f"search_partner failed: {e}")
            print(json.dumps([]))
            return []

    def create_invoice(self, partner_name: str, amount: float, description: str) -> dict:
        """Create a customer invoice. HITL if amount > HITL_LIMIT."""
        params = {"partner": partner_name, "amount": amount, "description": description}
        logger.info(f"create_invoice: {params}")

        if amount > HITL_LIMIT and not self.force:
            _hitl_pending("create_invoice", params,
                          f"Invoice amount ${amount:.2f} exceeds ${HITL_LIMIT:.0f} threshold")
            _audit_log("create_invoice", params, "hitl_pending", f"amount ${amount} > limit")
            return {"status": "pending_approval"}

        if self.dry_run:
            result = {"status": "dry-run", "invoice_id": 0, "partner": partner_name,
                      "amount": amount, "description": description}
            _audit_log("create_invoice", params, "dry-run", str(result))
            print(json.dumps(result))
            return result

        try:
            # Find partner
            partner_ids = self._call("res.partner", "search", [[["name", "ilike", partner_name]]])
            if not partner_ids:
                raise ValueError(f"Partner not found: {partner_name}")
            partner_id = partner_ids[0]

            # Find product (use first service product if available)
            prod_ids = self._call("product.product", "search",
                                  [[["name", "ilike", "Service"]]], {"limit": 1})
            product_id = prod_ids[0] if prod_ids else False

            invoice_vals = {
                "partner_id":   partner_id,
                "move_type":    "out_invoice",
                "invoice_line_ids": [(0, 0, {
                    "name":       description,
                    "price_unit": amount,
                    "product_id": product_id,
                    "quantity":   1,
                })],
            }
            invoice_id = self._call("account.move", "create", [invoice_vals])
            # Confirm the invoice
            self._call("account.move", "action_post", [[invoice_id]])
            result = {"status": "success", "invoice_id": invoice_id,
                      "partner": partner_name, "amount": amount}
            _audit_log("create_invoice", params, "success", f"invoice_id={invoice_id}")
            print(json.dumps(result))
            return result
        except Exception as e:
            _audit_log("create_invoice", params, "error", str(e))
            logger.error(f"create_invoice failed: {e}")
            result = {"status": "error", "error": str(e)}
            print(json.dumps(result))
            return result

    def post_payment(self, invoice_id: int, amount: float) -> dict:
        """Register payment against an invoice. HITL if amount > HITL_LIMIT."""
        params = {"invoice_id": invoice_id, "amount": amount}
        logger.info(f"post_payment: {params}")

        if amount > HITL_LIMIT and not self.force:
            _hitl_pending("post_payment", params,
                          f"Payment amount ${amount:.2f} exceeds ${HITL_LIMIT:.0f} threshold")
            _audit_log("post_payment", params, "hitl_pending", f"amount ${amount} > limit")
            return {"status": "pending_approval"}

        if self.dry_run:
            result = {"status": "dry-run", "invoice_id": invoice_id, "amount": amount}
            _audit_log("post_payment", params, "dry-run", str(result))
            print(json.dumps(result))
            return result

        try:
            payment_vals = {
                "payment_type":            "inbound",
                "partner_type":            "customer",
                "amount":                  amount,
                "reconciled_invoice_ids":  [(4, invoice_id)],
            }
            payment_id = self._call("account.payment", "create", [payment_vals])
            self._call("account.payment", "action_post", [[payment_id]])
            result = {"status": "success", "payment_id": payment_id,
                      "invoice_id": invoice_id, "amount": amount}
            _audit_log("post_payment", params, "success", f"payment_id={payment_id}")
            print(json.dumps(result))
            return result
        except Exception as e:
            _audit_log("post_payment", params, "error", str(e))
            logger.error(f"post_payment failed: {e}")
            result = {"status": "error", "error": str(e)}
            print(json.dumps(result))
            return result

    def get_balance(self) -> dict:
        """Get total outstanding receivables (unpaid invoices)."""
        params = {}
        logger.info("get_balance")

        if self.dry_run:
            result = {"status": "dry-run", "outstanding_receivables": 0.0,
                      "unpaid_invoices": 0, "currency": "USD"}
            _audit_log("get_balance", params, "dry-run", str(result))
            print(json.dumps(result))
            return result

        try:
            # Unpaid confirmed invoices
            inv_ids = self._call("account.move", "search",
                                 [[["move_type", "=", "out_invoice"],
                                   ["state", "=", "posted"],
                                   ["payment_state", "in", ["not_paid", "partial"]]]])
            invoices = self._call("account.move", "read", [inv_ids],
                                  {"fields": ["name", "amount_residual", "currency_id"]}) if inv_ids else []
            total = sum(i.get("amount_residual", 0) for i in invoices)
            result = {"status": "success", "outstanding_receivables": round(total, 2),
                      "unpaid_invoices": len(invoices), "currency": "USD"}
            _audit_log("get_balance", params, "success", str(result))
            print(json.dumps(result))
            return result
        except Exception as e:
            _audit_log("get_balance", params, "error", str(e))
            logger.error(f"get_balance failed: {e}")
            result = {"status": "error", "error": str(e)}
            print(json.dumps(result))
            return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Odoo Accounting MCP")
    parser.add_argument("--action",      required=True,
                        choices=["create_invoice", "post_payment", "get_balance", "search_partner"])
    parser.add_argument("--partner",     default="")
    parser.add_argument("--amount",      type=float, default=0.0)
    parser.add_argument("--description", default="Service")
    parser.add_argument("--invoice-id",  type=int, default=0, dest="invoice_id")
    parser.add_argument("--name",        default="")
    parser.add_argument("--dry-run",     action="store_true")
    parser.add_argument("--force",       action="store_true",
                        help="Bypass HITL threshold (use when already approved by human)")
    args = parser.parse_args()

    odoo = OdooMCP(dry_run=args.dry_run, force=args.force)

    if args.action == "search_partner":
        odoo.search_partner(args.name or args.partner)
    elif args.action == "create_invoice":
        if not args.partner or args.amount <= 0:
            print(json.dumps({"status": "error", "error": "--partner and --amount required"}))
            sys.exit(1)
        odoo.create_invoice(args.partner, args.amount, args.description)
    elif args.action == "post_payment":
        if not args.invoice_id or args.amount <= 0:
            print(json.dumps({"status": "error", "error": "--invoice-id and --amount required"}))
            sys.exit(1)
        odoo.post_payment(args.invoice_id, args.amount)
    elif args.action == "get_balance":
        odoo.get_balance()


if __name__ == "__main__":
    main()
