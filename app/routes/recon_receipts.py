# app/routes/recon_receipts.py

from fastapi import APIRouter, UploadFile, File, Query
import os
import pandas as pd

from app.services.receipt_store import list_receipts
from app.services.match_receipts import match_receipts_to_bank

router = APIRouter()

EXPORT_DIR = "app/exports"
os.makedirs(EXPORT_DIR, exist_ok=True)


@router.post("/recon/match-receipts", tags=["Reconciliation"])
async def match_receipts_endpoint(
    bank_csv: UploadFile = File(..., description="Xero-like bank CSV (must include Date and Amount columns)"),
    date_window_days: int = Query(3, ge=0, le=14, description="Receipt date window in days"),
    amount_tol: float = Query(0.01, ge=0.0, le=5.0, description="Amount tolerance"),
):
    # Load bank CSV into DataFrame
    df = pd.read_csv(bank_csv.file)

    # Load receipts captured via OCR uploads
    receipts = list_receipts()

    enriched_df, summary = match_receipts_to_bank(
        df,
        receipts,
        date_window_days=date_window_days,
        amount_tol=amount_tol,
    )

    # Save enriched output beside exports
    out_name = os.path.splitext(bank_csv.filename)[0] + "_with_receipts.csv"
    out_path = os.path.join(EXPORT_DIR, out_name)
    enriched_df.to_csv(out_path, index=False, encoding="utf-8")

    return {
        "summary": summary,
        "export_file": out_name,
        "export_path": out_path,
        "rows": len(enriched_df),
    }
