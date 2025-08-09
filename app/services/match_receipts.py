# app/services/match_receipts.py

from __future__ import annotations
import math
from datetime import datetime
from typing import Iterable, Tuple

import pandas as pd
from dateutil import parser as dtparser


def _parse_date_safe(val) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    # Prefer day-first to handle 11/07/2025 etc.
    try:
        return dtparser.parse(s, dayfirst=True, fuzzy=True)
    except Exception:
        return None


def _norm_amount(val) -> float | None:
    if val is None or (isinstance(val, float) and (math.isnan(val))):
        return None
    s = str(val).replace(",", "").replace("BHD", "").strip()
    try:
        return float(s)
    except Exception:
        return None


def _within_days(d1: datetime, d2: datetime, days: int) -> bool:
    return abs((d1.date() - d2.date()).days) <= days


def match_receipts_to_bank(
    bank_df: pd.DataFrame,
    receipts: Iterable[dict],
    *,
    date_col_guess: str = "Date",
    amount_col_guess: str = "Amount",
    ref_col_guess: str | None = None,
    date_window_days: int = 3,
    amount_tol: float = 0.01,
) -> Tuple[pd.DataFrame, dict]:
    """
    Enrich bank_df with receipt matches.

    Assumptions:
      - bank_df has a date column (default 'Date')
      - bank_df has an amount column (default 'Amount')
      - receipts is an iterable of dicts: {id, amount, date, reference, ...}
    """

    df = bank_df.copy()

    # Normalize bank dates & amounts
    bank_date_col = date_col_guess if date_col_guess in df.columns else next(
        (c for c in df.columns if c.lower().startswith("date")), date_col_guess
    )
    bank_amt_col = amount_col_guess if amount_col_guess in df.columns else next(
        (c for c in df.columns if "amount" in c.lower()), amount_col_guess
    )

    df["_BankDate"] = df[bank_date_col].apply(_parse_date_safe)
    df["_BankAmt"] = df[bank_amt_col].apply(_norm_amount)

    # Prepare receipts list with parsed fields
    recs = []
    for r in receipts:
        ra = _norm_amount(r.get("amount"))
        rd = _parse_date_safe(r.get("date"))
        if ra is None:
            # Skip receipts with no amount
            continue
        recs.append({
            "id": r.get("id"),
            "amount": abs(ra),  # compare by absolute
            "date": rd,
            "reference": r.get("reference"),
            "filename": r.get("filename"),
            "source": r.get("source"),
        })

    # Index to prevent double-using the same receipt
    used_receipt_ids: set[str] = set()

    # Output columns
    df["MatchedReceiptID"] = None
    df["MatchedReceiptRef"] = None
    df["MatchedReceiptDate"] = None
    df["MatchedReceiptFile"] = None
    df["ReceiptCandidates"] = None
    df["ReviewStatus_Receipt"] = None

    total_rows = len(df)
    matched = 0
    dup_candidates = 0
    no_candidates = 0
    multi_candidates = 0

    for idx, row in df.iterrows():
        b_amt = row["_BankAmt"]
        b_date = row["_BankDate"]

        # Only attempt if we have a valid amount
        if b_amt is None:
            df.at[idx, "ReviewStatus_Receipt"] = "No Amount – Skip"
            no_candidates += 1
            continue

        # Candidate receipts by amount tolerance
        cand = [r for r in recs if abs(abs(b_amt) - r["amount"]) <= amount_tol]

        # If we have a date on the bank row, filter by window
        if b_date is not None:
            cand = [r for r in cand if r["date"] is None or _within_days(b_date, r["date"], date_window_days)]

        if not cand:
            df.at[idx, "ReviewStatus_Receipt"] = "No Receipt Found"
            no_candidates += 1
            continue

        # Prefer unused receipts first
        primary = [r for r in cand if r["id"] not in used_receipt_ids]
        chosen = None

        if len(primary) == 1:
            chosen = primary[0]
        elif len(primary) > 1:
            # still ambiguous – leave candidates for review
            df.at[idx, "ReceiptCandidates"] = [r["id"] for r in primary]
            df.at[idx, "ReviewStatus_Receipt"] = "Multiple Receipt Candidates – Review"
            multi_candidates += 1
        else:
            # All candidates already used – flag duplicate usage
            df.at[idx, "ReceiptCandidates"] = [r["id"] for r in cand]
            df.at[idx, "ReviewStatus_Receipt"] = "Duplicate Receipt Use – Review"
            dup_candidates += 1

        if chosen:
            used_receipt_ids.add(chosen["id"])
            df.at[idx, "MatchedReceiptID"] = chosen["id"]
            df.at[idx, "MatchedReceiptRef"] = chosen.get("reference")
            df.at[idx, "MatchedReceiptDate"] = (
                chosen["date"].date().isoformat() if isinstance(chosen["date"], datetime) else None
            )
            df.at[idx, "MatchedReceiptFile"] = chosen.get("filename")
            df.at[idx, "ReviewStatus_Receipt"] = "Matched via Receipt"
            matched += 1

    summary = {
        "bank_rows": total_rows,
        "matched": matched,
        "no_candidates": no_candidates,
        "multi_candidates": multi_candidates,
        "duplicate_receipt_use": dup_candidates,
    }

    # Clean up temp columns
    df.drop(columns=["_BankDate", "_BankAmt"], inplace=True, errors="ignore")
    return df, summary
