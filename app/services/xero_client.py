# services/xero_client.py

import hashlib
import json
import httpx
from typing import Dict, Any, List, Optional
from app.utils.token_utils import get_access_token, get_tenant_id

XERO_API_BASE = "https://api.xero.com/api.xro/2.0"

def _headers(idem_key: Optional[str] = None) -> Dict[str, str]:
    access_token = get_access_token()
    tenant_id = get_tenant_id()
    h = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Xero-tenant-id": tenant_id,
    }
    if idem_key:
        h["Idempotency-Key"] = idem_key
    return h

async def list_accounts() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{XERO_API_BASE}/Accounts", headers=_headers())
        r.raise_for_status()
        return r.json()

def make_idem_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

async def post_payments(payments: List[Dict[str, Any]], idem_seed: str) -> Dict[str, Any]:
    # Xero allows batch POST: {"Payments":[ ... ]}
    body = {"Payments": payments}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            f"{XERO_API_BASE}/Payments",
            headers=_headers(idem_key=make_idem_key(idem_seed, "payments", json.dumps(body, sort_keys=True))),
            json=body
        )
        r.raise_for_status()
        return r.json()

async def post_bank_transactions(transactions: List[Dict[str, Any]], idem_seed: str) -> Dict[str, Any]:
    body = {"BankTransactions": transactions}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            f"{XERO_API_BASE}/BankTransactions",
            headers=_headers(idem_key=make_idem_key(idem_seed, "banktxns", json.dumps(body, sort_keys=True))),
            json=body
        )
        r.raise_for_status()
        return r.json()
