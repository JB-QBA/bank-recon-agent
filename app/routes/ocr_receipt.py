# app/routes/ocr_receipt.py

from fastapi import APIRouter, UploadFile, File
import shutil
import os
from app.services.ocr_parser import extract_receipt_data

router = APIRouter()

RECEIPT_DIR = "app/receipts"
os.makedirs(RECEIPT_DIR, exist_ok=True)

@router.post("/upload/payment-receipt")
async def upload_payment_receipt(file: UploadFile = File(...)):
    file_path = os.path.join(RECEIPT_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    extracted = extract_receipt_data(file_path)
    return {
        "filename": file.filename,
        "extracted": extracted
    }
