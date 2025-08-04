# app/routes/xero_data.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.utils.token_utils import get_access_token
import httpx

router = APIRouter()

class PaymentRequest(BaseModel):
    invoice_id: str
    account_id: str
    amount: float
    date: str  # YYYY-MM-DD
    currency_rate: float | None = None  # ✅ Optional for foreign currency

async def get_tenant_id(access_token: str):
    async with httpx.AsyncClient() as client:
        conn_response = await client.get(
            "https://api.xero.com/connections",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        connections = conn_response.json()
        if not connections:
            raise HTTPException(status_code=400, detail="No Xero tenant connected.")
        return connections[0]["tenantId"]

@router.get("/invoices")
async def get_unpaid_invoices():
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)

    async with httpx.AsyncClient() as client:
        invoices_response = await client.get(
            "https://api.xero.com/api.xro/2.0/Invoices?where=Type==\"ACCPAY\"&&Status==\"AUTHORISED\"",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-tenant-id": tenant_id,
                "Accept": "application/json"
            }
        )

    invoices = invoices_response.json().get("Invoices", [])
    return [
        {
            "InvoiceID": i["InvoiceID"],
            "InvoiceNumber": i["InvoiceNumber"],
            "Contact": i["Contact"]["Name"],
            "AmountDue": i["AmountDue"],
            "DueDate": i["DueDate"]
        }
        for i in invoices
    ]

@router.get("/contacts")
async def get_contacts():
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.xero.com/api.xro/2.0/Contacts",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-tenant-id": tenant_id,
                "Accept": "application/json"
            }
        )

    contacts = response.json().get("Contacts", [])
    return [
        {
            "ContactID": c["ContactID"],
            "Name": c["Name"],
            "Email": c.get("EmailAddress"),
            "Status": c.get("ContactStatus")
        }
        for c in contacts
    ]

@router.post("/payments")
async def create_payment(payment: PaymentRequest):
    access_token = await get_access_token()
    tenant_id = await get_tenant_id(access_token)

    payment_data = {
        "Invoice": {"InvoiceID": payment.invoice_id},
        "Account": {"AccountID": payment.account_id},
        "Amount": payment.amount,
        "Date": payment.date
    }

    if payment.currency_rate:
        payment_data["CurrencyRate"] = payment.currency_rate  # ✅ Include only if set

    async with httpx.AsyncClient() as client:
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
        raise HTTPException(status_code=500, detail=response.json())

    return response.json()
