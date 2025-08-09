# app/services/receipt_store.py

import json
import os
from uuid import uuid4
from datetime import datetime, timezone

RECEIPT_DIR = "app/receipts"
RECEIPT_STORE = os.path.join(RECEIPT_DIR, "receipts.json")

os.makedirs(RECEIPT_DIR, exist_ok=True)
if not os.path.exists(RECEIPT_STORE):
    with open(RECEIPT_STORE, "w", encoding="utf-8") as f:
        json.dump([], f)


def _load() -> list[dict]:
    with open(RECEIPT_STORE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: list[dict]) -> None:
    with open(RECEIPT_STORE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_receipt(*, filename: str, amount: float | None, date_iso: str | None,
                reference: str | None, raw_text: str | None, source_hint: str | None = None) -> dict:
    """Append one parsed receipt to the local store and return the saved record."""
    rec = {
        "id": str(uuid4()),
        "filename": filename,
        "amount": amount,
        "date": date_iso,          # 'YYYY-MM-DD' or None
        "reference": reference,
        "raw_text": raw_text,
        "source": source_hint,
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    data = _load()
    data.append(rec)
    _save(data)
    return rec


def list_receipts() -> list[dict]:
    return _load()


def clear_receipts() -> int:
    """Dangerous. Clears the store. Returns number removed."""
    data = _load()
    _save([])
    return len(data)
