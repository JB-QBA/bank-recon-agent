# app/routes/xero_data.py

from fastapi import APIRouter
from app.utils.token_utils import get_access_token
import httpx

router = APIRouter()

@router.get("/invoices")
async def get_unpaid_invoices():
    access_token = await get_access_token()

    # Step 1: Get tenant ID
    async with httpx.AsyncClient() as client:
        conn_response = await client.get(
            "https://api.xero.com/connections",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        connections = conn_response.json()
        if not connections:
            return {"error": "No tenant connection found."}
        tenant_id = connections[0]["tenantId"]

        # Step 2: Get unpaid purchase bills
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
            "InvoiceNumber": i["InvoiceNumber"],
            "Contact": i["Contact"]["Name"],
            "AmountDue": i["AmountDue"],
            "DueDate": i["DueDate"]
        }
        for i in invoices
    ]
