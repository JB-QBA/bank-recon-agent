# app/services/payment_orchestrator.py

from typing import Dict, Any, List, Tuple
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import json

from app.services.xero_client import post_payments, post_bank_transactions
from app.services.xero_client import make_idem_key  # (kept for compatibility if you use it elsewhere)

LOG_PATH = Path("/app/exports/xero_post_log.jsonl")

def _round2(v: float | Decimal) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _round_rate6(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

def pick_bank_account_id(accounts_json: Dict[str, Any], hint: str | None) -> Tuple[str, Dict[str, Any]]:
    """
    Choose the first ACTIVE BANK account, optionally filtered by name/code substring.
    Returns (AccountID, account_json).
    """
    candidates = [
        a for a in accounts_json.get("Accounts", [])
        if a.get("Type") == "BANK" and a.get("Status") == "ACTIVE"
    ]
    if not candidates:
        raise ValueError("No active BANK accounts found in Xero.")

    if hint:
        for a in candidates:
            hay = (a.get("Name", "") + " " + a.get("Code", "")).lower()
            if hint.lower() in hay:
                return a["AccountID"], a

    return candidates[0]["AccountID"], candidates[0]

def validate_and_build(payload: Dict[str, Any], bank_account_id: str) -> Dict[str, Any]:
    """
    Validates request JSON and builds Xero payloads for:
      - Payments (for invoice allocations) with auto FX CurrencyRate
      - BankTransactions (SPEND/RECEIVE) for non-invoice lines

    Expected payload (abridged):
    {
      "lines": [
        {
          "bank_line_id": "...",
          "date": "YYYY-MM-DD",
          "amount": -2000.00,            # local bank amount (signed)
          "type": "invoices",
          "invoices": [{"invoice_id": "...", "amount": 100.00}]  # foreign totals
        },
        {
          "type": "non_invoice",
          "non_invoice": {
            "is_spend": true,
            "account_code": "4205",      # OR: "account_id": "xxx-..."
            "contact_id": "xxx-...",
            "description": "..."
          }
        }
      ],
      "config": { "require_exact_totals": true, "amount_tolerance": 0.01 }
    }
    """
    cfg = payload.get("config", {}) or {}
    tol = Decimal(str(cfg.get("amount_tolerance", 0.01)))
    require_exact = bool(cfg.get("require_exact_totals", True))

    payments: List[Dict[str, Any]] = []
    banktxns: List[Dict[str, Any]] = []
    preview_items: List[Dict[str, Any]] = []

    for ln in payload["lines"]:
        bank_line_id = ln["bank_line_id"]
        date = ln["date"]
        amt_local_signed = _round2(ln["amount"])
        reference = (ln.get("reference") or "").strip()
        kind = ln["type"]

        if kind == "invoices":
            invs = ln.get("invoices") or []
            if not invs:
                raise ValueError(f"[{bank_line_id}] Missing 'invoices' allocations.")

            foreign_total = _round2(sum(_round2(i["amount"]) for i in invs))
            if foreign_total <= Decimal("0.00"):
                raise ValueError(f"[{bank_line_id}] Sum of invoice amounts must be > 0.")

            local_total_abs = _round2(abs(amt_local_signed))

            if require_exact and abs(local_total_abs - foreign_total) > tol:
                raise ValueError(
                    f"[{bank_line_id}] Foreign total {foreign_total} != local abs {local_total_abs} (tol {tol}). "
                    f"If bank fees are included, post them as a separate 'non_invoice' line; "
                    f"or disable 'require_exact_totals'."
                )

            # Auto FX rate so local = bank amount on reconciliation
            currency_rate = _round_rate6(local_total_abs / foreign_total) if foreign_total > 0 else None

            for i in invs:
                pay = {
                    "Invoice": {"InvoiceID": i["invoice_id"]},
                    "Account": {"AccountID": bank_account_id},
                    "Date": date,
                    "Amount": float(_round2(i["amount"])),  # foreign (invoice currency)
                    "Reference": reference[:255] if reference else None
                }
                if currency_rate is not None:
                    pay["CurrencyRate"] = float(currency_rate)
                payments.append(pay)
                preview_items.append({"bank_line_id": bank_line_id, "type": "payment", "payload": pay})

        elif kind == "non_invoice":
            ni = ln.get("non_invoice") or {}
            is_spend = bool(ni.get("is_spend"))
            contact_id = ni.get("contact_id")

            # ✅ safeguard: require a contact for SPEND (Xero validation)
            if is_spend and not contact_id:
                raise ValueError(f"[{bank_line_id}] 'contact_id' is required for SPEND money transactions.")

            # ✅ support AccountCode OR AccountID
            account_code = ni.get("account_code")
            account_id = ni.get("account_id")
            if not account_code and not account_id:
                raise ValueError(f"[{bank_line_id}] Provide either 'account_code' or 'account_id' for non_invoice line.")

            line_amt_local_abs = float(abs(amt_local_signed))

            line_item: Dict[str, Any] = {
                "Description": ni.get("description") or reference or ("Spend Money" if is_spend else "Receive Money"),
                "Quantity": 1,
                "UnitAmount": line_amt_local_abs,
                "TaxType": "NONE"
            }
            if account_id:
                line_item["AccountID"] = account_id
            else:
                line_item["AccountCode"] = account_code

            banktxn = {
                "Type": "SPEND" if is_spend else "RECEIVE",
                "Contact": ({"ContactID": contact_id} if contact_id else None),
                "Date": date,
                "Reference": reference[:255] if reference else None,
                "BankAccount": {"AccountID": bank_account_id},
                "LineItems": [line_item]
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
