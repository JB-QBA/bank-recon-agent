# app/routes/xero_data.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Dict, Any
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import json
import hashlib
import httpx

from app.utils.token_utils import get_access_token

router = APIRouter()

# -------------------------
# Existing models & helpers
# -------------------------

class PaymentRequest(BaseModel):
    invoice_id: str
    account_id: str
    amount: float
    date: str  # YYYY-MM-DD
    currency_rate: float | None = None  # Optional for foreign currency

async def get_tenant_id(access_token: str):
    async with httpx.AsyncClient(timeout=60) as client:
        conn_response = await client.get(
            "https://api.xero.com/connections",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if conn_response.status_code != 200:
            raise HTTPException(status_code=conn_response.status_code, detail=conn_response.text)
        connections = conn_response.json()
        if not connections:
            raise HTTPException(status_code=400, detail="No Xero tenant connected.")
        return connections[0]["tenantId"]

# -------------------------
# Existing endpoints (kept)
# -------------------------

@router.get("/invoices")
async def get_unpaid_invoices():
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)

    async with httpx.AsyncClient(timeout=60) as client:
        invoices_response = await client.get(
            "https://api.xero.com/api.xro/2.0/Invoices?where=Type==\"ACCPAY\"&&Status==\"AUTHORISED\"",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-tenant-id": tenant_id,
                "Accept": "application/json"
            }
        )

    if invoices_response.status_code != 200:
        raise HTTPException(status_code=invoices_response.status_code, detail=invoices_response.text)

    invoices = invoices_response.json().get("Invoices", [])
    return [
        {
            "InvoiceID": i.get("InvoiceID"),
            "InvoiceNumber": i.get("InvoiceNumber"),
            "Contact": i.get("Contact", {}).get("Name"),
            "AmountDue": i.get("AmountDue"),
            "DueDate": i.get("DueDate")
        }
        for i in invoices
    ]

@router.get("/contacts")
async def get_contacts():
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(
            "https://api.xero.com/api.xro/2.0/Contacts",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-tenant-id": tenant_id,
                "Accept": "application/json"
            }
        )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    contacts = response.json().get("Contacts", [])
    return [
        {
            "ContactID": c.get("ContactID"),
            "Name": c.get("Name"),
            "Email": c.get("EmailAddress"),
            "Status": c.get("ContactStatus")
        }
        for c in contacts
    ]

@router.post("/payments")
async def create_payment(payment: PaymentRequest):
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)

    payment_data: Dict[str, Any] = {
        "Invoice": {"InvoiceID": payment.invoice_id},
        "Account": {"AccountID": payment.account_id},
        "Amount": payment.amount,
        "Date": payment.date
    }
    if payment.currency_rate:
        payment_data["CurrencyRate"] = payment.currency_rate

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.xero.com/api.xro/2.0/Payments",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-tenant-id": tenant_id,
                "Accept": "application/json",
                "Content-Type": "application/json"
            },
            json=payment_data
        )

    if response.status_code != 200:
        try:
            raise HTTPException(status_code=response.status_code, detail=response.json())
        except Exception:
            raise HTTPException(status_code=response.status_code, detail=response.text)

    return response.json()

# --------------------------------------
# New: Accounts + Preview/Post endpoints
# --------------------------------------

class InvoiceAllocation(BaseModel):
    invoice_id: str
    amount: float

class NonInvoicePayload(BaseModel):
    is_spend: bool
    account_code: str
    contact_id: Optional[str] = None
    description: Optional[str] = None

class LineItem(BaseModel):
    bank_line_id: str
    date: str
    amount: float  # positive = receive, negative = spend
    reference: Optional[str] = None
    type: Literal["invoices", "non_invoice"]
    invoices: Optional[List[InvoiceAllocation]] = None
    non_invoice: Optional[NonInvoicePayload] = None

class PaymentsBatchRequest(BaseModel):
    bank_account_hint: Optional[str] = Field(default=None, description="Substring match on bank account Name/Code")
    lines: List[LineItem]
    config: Optional[Dict[str, Any]] = Field(default_factory=dict)

def _round2(v: float) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _idem_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

async def _list_accounts(access_token: str, tenant_id: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            "https://api.xero.com/api.xro/2.0/Accounts",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-tenant-id": tenant_id,
                "Accept": "application/json"
            }
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

def _pick_bank_account_id(accounts_json: Dict[str, Any], hint: Optional[str]) -> (str, Dict[str, Any]):
    accts = [a for a in accounts_json.get("Accounts", []) if a.get("Type") == "BANK" and a.get("Status") == "ACTIVE"]
    if not accts:
        raise HTTPException(status_code=400, detail="No active BANK accounts found in Xero.")
    if hint:
        for a in accts:
            if hint.lower() in (f"{a.get('Name','')} {a.get('Code','')}".lower()):
                return a["AccountID"], a
    return accts[0]["AccountID"], accts[0]

def _validate_and_build(payload: PaymentsBatchRequest, bank_account_id: str) -> Dict[str, Any]:
    cfg = payload.config or {}
    tol = Decimal(str(cfg.get("amount_tolerance", 0.01)))
    require_exact = bool(cfg.get("require_exact_totals", True))

    payments: List[Dict[str, Any]] = []
    banktxns: List[Dict[str, Any]] = []
    preview_items: List[Dict[str, Any]] = []

    for ln in payload.lines:
        bank_line_id = ln.bank_line_id
        date = ln.date
        amt = _round2(ln.amount)
        reference = (ln.reference or "").strip()

        if ln.type == "invoices":
            if not ln.invoices:
                raise HTTPException(status_code=400, detail=f"[{bank_line_id}] Missing 'invoices' allocations.")
            total_apply = _round2(sum(_round2(i.amount) for i in ln.invoices))
            if require_exact and abs(total_apply - amt) > tol:
                raise HTTPException(
                    status_code=400,
                    detail=f"[{bank_line_id}] Invoice allocations {total_apply} != bank amount {amt} (tol {tol})."
                )
            for i in ln.invoices:
                p = {
                    "Invoice": {"InvoiceID": i.invoice_id},
                    "Account": {"AccountID": bank_account_id},
                    "Date": date,
                    "Amount": float(_round2(i.amount)),
                    "Reference": reference[:255] if reference else None
                }
                payments.append(p)
                preview_items.append({"bank_line_id": bank_line_id, "type": "payment", "payload": p})

        elif ln.type == "non_invoice":
            if not ln.non_invoice:
                raise HTTPException(status_code=400, detail=f"[{bank_line_id}] Missing 'non_invoice' payload.")
            ni = ln.non_invoice
            is_spend = bool(ni.is_spend)
            line_amt = float(abs(amt))
            txn = {
                "Type": "SPEND" if is_spend else "RECEIVE",
                "Contact": ({"ContactID": ni.contact_id} if ni.contact_id else None),
                "Date": date,
                "Reference": reference[:255] if reference else None,
                "BankAccount": {"AccountID": bank_account_id},
                "LineItems": [{
                    "Description": ni.description or reference or ("Spend Money" if is_spend else "Receive Money"),
                    "AccountCode": ni.account_code,
                    "Quantity": 1,
                    "UnitAmount": line_amt,
                    "TaxType": "NONE"
                }]
            }
            banktxns.append(txn)
            preview_items.append({"bank_line_id": bank_line_id, "type": "banktxn", "payload": txn})

        else:
            raise HTTPException(status_code=400, detail=f"[{bank_line_id}] Unknown line type: {ln.type}")

    return {"payments": payments, "banktxns": banktxns, "preview": preview_items}

async def _post_payments(access_token: str, tenant_id: str, body: Dict[str, Any], idem_key: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.xero.com/api.xro/2.0/Payments",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-tenant-id": tenant_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Idempotency-Key": idem_key
            },
            json=body
        )
        if r.status_code not in (200, 201):
            try:
                raise HTTPException(status_code=r.status_code, detail=r.json())
            except Exception:
                raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

async def _post_bank_transactions(access_token: str, tenant_id: str, body: Dict[str, Any], idem_key: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.xero.com/api.xro/2.0/BankTransactions",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-tenant-id": tenant_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Idempotency-Key": idem_key
            },
            json=body
        )
        if r.status_code not in (200, 201):
            try:
                raise HTTPException(status_code=r.status_code, detail=r.json())
            except Exception:
                raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

_AUDIT_LOG = Path("/app/exports/xero_post_log.jsonl")

def _append_audit(records: List[Dict[str, Any]]) -> None:
    _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _AUDIT_LOG.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

@router.get("/accounts")
async def get_accounts(hint: Optional[str] = None):
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)
    data = await _list_accounts(access_token, tenant_id)
    bank_account_id, chosen = _pick_bank_account_id(data, hint)
    return {
        "chosen_bank_account_id": bank_account_id,
        "chosen_summary": {
            "Name": chosen.get("Name"),
            "Code": chosen.get("Code"),
            "CurrencyCode": chosen.get("CurrencyCode"),
        },
        "accounts_raw": data,
    }

@router.post("/payments/preview")
async def payments_preview(req: PaymentsBatchRequest):
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)

    accounts = await _list_accounts(access_token, tenant_id)
    bank_account_id, chosen = _pick_bank_account_id(accounts, req.bank_account_hint)

    validated = _validate_and_build(req, bank_account_id)
    return {
        "bank_account_id": bank_account_id,
        "bank_account_name": chosen.get("Name"),
        "to_post_counts": {
            "payments": len(validated["payments"]),
            "banktxns": len(validated["banktxns"])
        },
        "items": validated["preview"]
    }

@router.post("/payments/post")
async def payments_post(req: PaymentsBatchRequest):
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)

    accounts = await _list_accounts(access_token, tenant_id)
    bank_account_id, chosen = _pick_bank_account_id(accounts, req.bank_account_hint)

    validated = _validate_and_build(req, bank_account_id)

    seed = _idem_key(
        (req.bank_account_hint or chosen.get("Name") or bank_account_id),
        json.dumps(req.model_dump(), sort_keys=True)
    )

    results: Dict[str, Any] = {"payments_result": None, "banktxns_result": None}

    if validated["payments"]:
        body = {"Payments": validated["payments"]}
        results["payments_result"] = await _post_payments(
            access_token, tenant_id, body, _idem_key(seed, "payments")
        )

    if validated["banktxns"]:
        body = {"BankTransactions": validated["banktxns"]}
        results["banktxns_result"] = await _post_bank_transactions(
            access_token, tenant_id, body, _idem_key(seed, "banktxns")
        )

    from datetime import datetime, timezone
    audit_records = []
    for item in validated["preview"]:
        audit_records.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "bank_line_id": item.get("bank_line_id"),
            "type": item.get("type"),
            "request": item.get("payload"),
            "xero_response_keys": {
                "payments": bool(results["payments_result"]),
                "banktxns": bool(results["banktxns_result"])
            }
        })
    _append_audit(audit_records)

    return {
        "bank_account": {"id": bank_account_id, "name": chosen.get("Name")},
        "posted": {
            "payments": len(validated["payments"]),
            "banktxns": len(validated["banktxns"])
        },
        "xero_results": results
    }
