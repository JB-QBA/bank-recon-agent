# app/routes/xero_auth.py

import os
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
import httpx
from urllib.parse import urlencode

router = APIRouter()

CLIENT_ID = os.getenv("XERO_CLIENT_ID")
CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")
REDIRECT_URI = os.getenv("XERO_REDIRECT_URI")

SCOPES = "openid profile email accounting.transactions accounting.contacts"

@router.get("/authorize")
def authorize():
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
    code = request.query_params.get("code")

    token_url = "https://identity.xero.com/connect/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data, headers=headers)
        token_data = response.json()

    return token_data  # or save this securely
