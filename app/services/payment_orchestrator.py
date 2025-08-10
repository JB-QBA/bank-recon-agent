# services/payment_orchestrator.py

from typing import Dict, Any, List, Tuple
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import json
from app.services.xero_client import post_payments, post_bank_transactions
from app.services.xero_client import make_idem_key

LOG_PATH = Path("/app/exports/xero_post_log.jsonl")

def _round2(v: float) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def pick_bank_account_id(accounts_json: Dict[str, Any], hint: str | None) -> Tuple[str, Dict[str, Any]]:
    # Choose the first account where Type == "BANK" and Name/Code contains hint (if provided)
    candidates = [a for a in accounts_json.get("Accounts", []) if a.get("Type") == "BANK" and a.get("Status") == "ACTIVE"]
    if hint:
        for a in candidates:
            if hint.lower() in (a.get("Name","") + " " + a.get("Code","")).lower():
                return a["AccountID"], a
    if not candidates:
        raise ValueError("No active BANK accounts found in Xero.")
    return candidates[0]["AccountID"], candidates[0]

def validate_and_build(payload: Dict[str, Any], bank_account_id: str) -> Dict[str, Any]:
    cfg = payload.get("config", {}) or {}
    tol = Decimal(str(cfg.get("amount_tolerance", 0.01)))
    require_exact = bool(cfg.get("require_exact_totals", True))

    payments: List[Dict[str, Any]] = []
    banktxns: List[Dict[str, Any]] = []
    preview_items: List[Dict[str, Any]] = []

    for ln in payload["lines"]:
        bank_line_id = ln["bank_line_id"]
        date = ln["date"]
        amt = _round2(ln["amount"])
        reference = ln.get("reference","").strip()
        kind = ln["type"]

        if kind == "invoices":
            invs = ln.get("invoices", [])
            total_apply = _round2(sum(_round2(i["amount"]) for i in invs))
            if require_exact and abs(total_apply - amt) > tol:
                raise ValueError(f"[{bank_line_id}] Invoice allocations {total_apply} do not equal bank amount {amt} within tolerance {tol}.")
            for i in invs:
                pay = {
                    "Invoice": {"InvoiceID": i["invoice_id"]},
                    "Account": {"AccountID": bank_account_id},  # source bank account
                    "Date": date,
                    "Amount": float(_round2(i["amount"])),
                    "Reference": reference[:255] if reference else None
                }
                payments.append(pay)
                preview_items.append({"bank_line_id": bank_line_id, "type": "payment", "payload": pay})

        elif kind == "non_invoice":
            ni = ln["non_invoice"]
            is_spend = bool(ni["is_spend"])
            line_amt = float(abs(amt))
            txn_type = "SPEND" if is_spend else "RECEIVE"
            banktxn = {
                "Type": "SPEND" if is_spend else "RECEIVE",
                "Contact": ({"ContactID": ni["contact_id"]} if ni.get("contact_id") else None),
                "Date": date,
                "Reference": reference[:255] if reference else None,
                "BankAccount": {"AccountID": bank_account_id},
                "LineItems": [{
                    "Description": ni.get("description") or reference or ( "Spend Money" if is_spend else "Receive Money"),
                    "AccountCode": ni["account_code"],
                    "Quantity": 1,
                    "UnitAmount": line_amt,
                    "TaxType": "NONE"  # adjust if needed
                }]
            }
            banktxns.append(banktxn)
            preview_items.append({"bank_line_id": bank_line_id, "type": "banktxn", "payload": banktxn})

        else:
            raise ValueError(f"[{bank_line_id}] Unknown line type: {kind}")

    return {"payments": payments, "banktxns": banktxns, "preview": preview_items}

async def post_to_xero(validated: Dict[str, Any], idem_seed: str) -> Dict[str, Any]:
    results = {"payments_result": None, "banktxns_result": None}
    if validated["payments"]:
        results["payments_result"] = await post_payments(validated["payments"], idem_seed)
    if validated["banktxns"]:
        results["banktxns_result"] = await post_bank_transactions(validated["banktxns"], idem_seed)
    return results

def append_audit_log(records: List[Dict[str, Any]]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
