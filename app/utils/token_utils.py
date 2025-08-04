# app/utils/token_utils.py

import os
import json
import time
import httpx

CLIENT_ID = os.getenv("XERO_CLIENT_ID")
CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")
REDIRECT_URI = os.getenv("XERO_REDIRECT_URI")

TOKEN_FILE = "xero_tokens.json"

def save_tokens(tokens: dict):
    """Save token data to file with calculated expiry"""
    tokens["expires_at"] = int(time.time()) + tokens.get("expires_in", 1800)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f)

def load_tokens():
    """Load token data from file"""
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, "r") as f:
        return json.load(f)

async def refresh_tokens(refresh_token: str):
    """Use refresh_token to get a new access_token"""
    token_url = "https://identity.xero.com/connect/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data, headers=headers)
        tokens = response.json()

    save_tokens(tokens)
    return tokens.get("access_token")

async def get_access_token():
    """Return valid access token (refresh if expired)"""
    tokens = load_tokens()
    if not tokens:
        raise Exception("No tokens found. Please authorize first.")

    if tokens["expires_at"] <= int(time.time()):
        return await refresh_tokens(tokens["refresh_token"])

    return tokens["access_token"]
