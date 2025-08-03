import requests
from typing import List
import datetime
import json
import os

# --- CONFIG ---
XERO_API_BASE = "https://api.xero.com/api.xro/2.0"
TENANT_ID = "your-xero-tenant-id"
ACCESS_TOKEN = "your-oauth-access-token"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config/bank_accounts.json")

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Accept": "application/json",
    "Xero-tenant-id": TENANT_ID,
    "Content-Type": "application/json"
}

# Load account codes from JSON config
def load_account_codes():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

BANK_ACCOUNT_CODES = load_account_codes()

def fetch_invoice(invoice_number: str):
    """
    Fetch a single invoice by invoice number from Xero.
    """
    url = f"{XERO_API_BASE}/Invoices?InvoiceNumber={invoice_number}"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    invoices = response.json().get("Invoices", [])
    return invoices[0] if invoices else None

def get_account_code(account_name: str) -> str:
    """
    Return the Xero account code for a known bank account name.
    Raises an error if no match is found.
    """
    account = BANK_ACCOUNT_CODES.get(account_name)
    if not account:
        raise ValueError(f"Unknown bank account name: '{account_name}'")
    return account["code"]

def create_payment(invoice_ids: List[str], amount: float, account_name: str, date: str = None):
    """
    Create a payment that splits across multiple invoices using a named bank account.
    """
    account_code = get_account_code(account_name)
    date = date or datetime.datetime.now().strftime("%Y-%m-%d")
    split_amount = round(amount / len(invoice_ids), 2)

    payments = []
    for invoice_id in invoice_ids:
        payments.append({
            "Invoice": {"InvoiceID": invoice_id},
            "Account": {"Code": account_code},
            "Date": date,
            "Amount": split_amount
        })

    url = f"{XERO_API_BASE}/Payments"
    response = requests.post(url, headers=HEADERS, json={"Payments": payments})
    response.raise_for_status()
    return response.json()
