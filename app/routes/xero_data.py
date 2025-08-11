# app/routes/xero_data.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Dict, Any
import json
import hashlib
import httpx

from app.utils.token_utils import get_access_token
from app.services.payment_orchestrator import (
    pick_bank_account_id,
    validate_and_build,
    post_to_xero,
    append_audit_log,
)

router = APIRouter()

# -------------------------
# Existing models & helpers
# -------------------------

class PaymentRequest(BaseModel):
    invoice_id: str
    account_id: str
    amount: float
    date: str  # YYYY-MM-DD
    currency_rate: float | None = None

async def get_tenant_id(access_token: str):
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            "https://api.xero.com/connections",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        conns = r.json()
        if not conns:
            raise HTTPException(status_code=400, detail="No Xero tenant connected.")
        return conns[0]["tenantId"]

# -------------------------
# Existing endpoints (kept)
# -------------------------

@router.get("/invoices")
async def get_unpaid_invoices():
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            'https://api.xero.com/api.xro/2.0/Invoices?where=Type=="ACCPAY"&&Status=="AUTHORISED"',
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-tenant-id": tenant_id,
                "Accept": "application/json"
            }
        )
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    invoices = r.json().get("Invoices", [])
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
        r = await client.get(
            "https://api.xero.com/api.xro/2.0/Contacts",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-tenant-id": tenant_id,
                "Accept": "application/json"
            }
        )
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    cs = r.json().get("Contacts", [])
    return [
        {"ContactID": c.get("ContactID"), "Name": c.get("Name"), "Email": c.get("EmailAddress"), "Status": c.get("ContactStatus")}
        for c in cs
    ]

@router.post("/payments")
async def create_payment(payment: PaymentRequest):
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)
    body: Dict[str, Any] = {
        "Invoice": {"InvoiceID": payment.invoice_id},
        "Account": {"AccountID": payment.account_id},
        "Amount": payment.amount,
        "Date": payment.date
    }
    if payment.currency_rate:
        body["CurrencyRate"] = payment.currency_rate
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.xero.com/api.xro/2.0/Payments",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-tenant-id": tenant_id,
                "Accept": "application/json",
                "Content-Type": "application/json"
            },
            json=body
        )
    if r.status_code != 200:
        try:
            raise HTTPException(status_code=r.status_code, detail=r.json())
        except Exception:
            raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()

# --------------------------------------
# New: Accounts + Preview/Post endpoints
# --------------------------------------

class InvoiceAllocation(BaseModel):
    invoice_id: str
    amount: float  # foreign (invoice currency)

class NonInvoicePayload(BaseModel):
    is_spend: bool
    account_code: Optional[str] = None  # now optional
    account_id: Optional[str] = None    # new: accept AccountID
    contact_id: Optional[str] = None
    description: Optional[str] = None

class LineItem(BaseModel):
    bank_line_id: str
    date: str
    amount: float  # local bank amount (signed)
    reference: Optional[str] = None
    type: Literal["invoices", "non_invoice"]
    invoices: Optional[List[InvoiceAllocation]] = None
    non_invoice: Optional[NonInvoicePayload] = None

class PaymentsBatchRequest(BaseModel):
    bank_account_hint: Optional[str] = Field(default=None)
    lines: List[LineItem]
    config: Optional[Dict[str, Any]] = Field(default_factory=dict)

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

@router.get("/accounts")
async def get_accounts(hint: Optional[str] = None):
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)
    data = await _list_accounts(access_token, tenant_id)
    bank_account_id, chosen = pick_bank_account_id(data, hint)
    return {
        "chosen_bank_account_id": bank_account_id,
        "chosen_summary": {"Name": chosen.get("Name"), "Code": chosen.get("Code"), "CurrencyCode": chosen.get("CurrencyCode")},
        "accounts_raw": data
    }

@router.post("/payments/preview")
async def payments_preview(req: PaymentsBatchRequest):
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)
    accounts = await _list_accounts(access_token, tenant_id)
    bank_account_id, chosen = pick_bank_account_id(accounts, req.bank_account_hint)
    validated = validate_and_build(req.model_dump(), bank_account_id)
    return {
        "bank_account_id": bank_account_id,
        "bank_account_name": chosen.get("Name"),
        "to_post_counts": {"payments": len(validated["payments"]), "banktxns": len(validated["banktxns"])},
        "items": validated["preview"]
    }

@router.post("/payments/post")
async def payments_post(req: PaymentsBatchRequest):
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)
    accounts = await _list_accounts(access_token, tenant_id)
    bank_account_id, chosen = pick_bank_account_id(accounts, req.bank_account_hint)

    payload = req.model_dump()
    validated = validate_and_build(payload, bank_account_id)

    seed = _idem_key((req.bank_account_hint or chosen.get("Name") or bank_account_id), json.dumps(payload, sort_keys=True))

    try:
        results = await post_to_xero(validated, seed)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Xero API error: {e}")

    # audit
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
    append_audit_log(audit_records)

    return {
        "bank_account": {"id": bank_account_id, "name": chosen.get("Name")},
        "posted": {"payments": len(validated["payments"]), "banktxns": len(validated["banktxns"])},
        "xero_results": results
    }
