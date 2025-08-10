# app/routes/xero_auth.py

import os
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
import httpx
from urllib.parse import urlencode

from app.utils.token_utils import save_tokens  # ✅ Save token data to file

router = APIRouter()

CLIENT_ID = os.getenv("XERO_CLIENT_ID")
CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")
REDIRECT_URI = os.getenv("XERO_REDIRECT_URI")

# ✅ Updated scopes:
# - offline_access: allows getting a refresh token for long-term use
# - accounting.transactions: needed for invoices, payments, bank transactions
# - accounting.settings: needed for listing accounts
# - accounting.contacts: needed for retrieving contacts
SCOPES = "offline_access accounting.transactions accounting.settings accounting.contacts"

@router.get("/authorize")
def authorize():
    """
    Step 1: Redirects user to Xero's login/consent screen.
    """
    query_params = urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": "xyz123"
    })
    return RedirectResponse(f"https://login.xero.com/identity/connect/authorize?{query_params}")

@router.get("/callback")
async def callback(request: Request):
    """
    Step 2: Handles Xero's callback after user grants access.
    Exchanges authorization code for access + refresh tokens.
    Saves tokens locally for reuse.
    """
    code = request.query_params.get("code")
    if not code:
        return {"error": "Missing code parameter in callback."}

    token_url = "https://identity.xero.com/connect/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(token_url, data=data, headers=headers)
        if response.status_code != 200:
            return {
                "error": "Failed to exchange code for tokens",
                "status_code": response.status_code,
                "details": response.text
            }
        tokens = response.json()

    # ✅ Save tokens to file so other endpoints can reuse them
    save_tokens(tokens)

    return {
        "message": "Xero authorization successful. Tokens saved.",
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "expires_in_minutes": tokens.get("expires_in", 0) // 60
    }
