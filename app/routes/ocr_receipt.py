# app/routes/ocr_receipt.py

from fastapi import APIRouter, UploadFile, File
import shutil
import os
from dateutil import parser as dtparser

from app.services.ocr_parser import extract_receipt_data
from app.services.receipt_store import add_receipt

router = APIRouter()

RECEIPT_DIR = "app/receipts"
os.makedirs(RECEIPT_DIR, exist_ok=True)


def _to_iso_date(datestr: str | None) -> str | None:
    if not datestr:
        return None
    try:
        return dtparser.parse(datestr, dayfirst=True, fuzzy=True).date().isoformat()
    except Exception:
        return None


@router.post("/upload/payment-receipt", tags=["Receipt OCR"])
async def upload_payment_receipt(file: UploadFile = File(...)):
    file_path = os.path.join(RECEIPT_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    extracted = extract_receipt_data(file_path)

    # Persist to local receipt store so matching can use it later
    saved = add_receipt(
        filename=file.filename,
        amount=float(extracted["amount"]) if extracted.get("amount") else None,
        date_iso=_to_iso_date(extracted.get("date")),
        reference=extracted.get("reference"),
        raw_text=extracted.get("text"),
        source_hint=None,
    )

    return {
        "filename": file.filename,
        "extracted": extracted,
        "saved": saved,
    }
