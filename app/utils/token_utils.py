# app/utils/token_utils.py

import os
import json
import time
from typing import Optional, Dict, Any
import httpx

CLIENT_ID = os.getenv("XERO_CLIENT_ID")
CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")
REDIRECT_URI = os.getenv("XERO_REDIRECT_URI")
ENV_TENANT_ID = os.getenv("XERO_TENANT_ID")  # optional override

TOKEN_FILE = "xero_tokens.json"
# Refresh a little early to be safe
EXPIRY_BUFFER_SECONDS = 60

def _now() -> int:
    return int(time.time())

def _with_expires_at(tokens: Dict[str, Any]) -> Dict[str, Any]:
    # Xero returns "expires_in" (seconds). Compute absolute "expires_at".
    ttl = int(tokens.get("expires_in", 1800))
    tokens["expires_at"] = _now() + ttl
    return tokens

def save_tokens(tokens: Dict[str, Any]) -> None:
    """Persist tokens (and any cached fields like tenant_id)."""
    # Ensure expires_at exists
    if "expires_at" not in tokens and "expires_in" in tokens:
        _with_expires_at(tokens)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f)

def load_tokens() -> Optional[Dict[str, Any]]:
    """Load tokens (and cached tenant_id) from disk."""
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def store_initial_tokens(tokens: Dict[str, Any], tenant_id: Optional[str] = None) -> None:
    """
    Call this right after the OAuth callback exchange.
    Optionally persist tenant_id if you already know it.
    """
    data = _with_expires_at(dict(tokens))
    if tenant_id:
        data["tenant_id"] = tenant_id
    save_tokens(data)

async def refresh_tokens(refresh_token: str) -> Dict[str, Any]:
    """
    Refresh access token using the current refresh_token.
    NOTE: Xero rotates the refresh_token. Always persist the returned one.
    """
    token_url = "https://identity.xero.com/connect/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        # "redirect_uri" is not required on refresh per Xero docs
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(token_url, data=data, headers=headers)
        if resp.status_code != 200:
            # Try to surface JSON error if available
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise RuntimeError(f"Xero token refresh failed: {detail}")

        tokens = resp.json()

    # Merge into existing token store to preserve cached fields (e.g., tenant_id)
    current = load_tokens() or {}
    current.update(tokens)  # includes new access_token, refresh_token, expires_in, etc.
    _with_expires_at(current)
    save_tokens(current)
    return current

async def get_access_token() -> str:
    """
    Return a valid access token. If expired (or about to), refresh first.
    """
    tokens = load_tokens()
    if not tokens:
        raise RuntimeError("No tokens found. Please complete Xero authorization first.")

    # Refresh if expiring soon
    if int(tokens.get("expires_at", 0)) <= _now() + EXPIRY_BUFFER_SECONDS:
        tokens = await refresh_tokens(tokens.get("refresh_token") or "")
    return tokens["access_token"]

async def get_tenant_id(access_token: Optional[str] = None) -> str:
    """
    Return the Xero tenant ID.
    - If XERO_TENANT_ID is set, prefer it.
    - Else, use cached tenant_id from token file if present.
    - Else, call /connections, cache the first tenantId, and return it.
    """
    if ENV_TENANT_ID:
        return ENV_TENANT_ID

    tokens = load_tokens()
    if tokens and tokens.get("tenant_id"):
        return tokens["tenant_id"]

    # Need to fetch via /connections
    if not access_token:
        access_token = await get_access_token()

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            "https://api.xero.com/connections",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if resp.status_code != 200:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise RuntimeError(f"Failed to fetch Xero connections: {detail}")

        conns = resp.json() or []

    if not conns:
        raise RuntimeError("No Xero tenant connected to this token.")

    tenant_id = conns[0].get("tenantId")
    # Cache it for next calls
    tokens = tokens or {}
    tokens["tenant_id"] = tenant_id
    save_tokens(tokens)
    return tenant_id
