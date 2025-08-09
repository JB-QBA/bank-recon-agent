# app/services/match_receipts.py

from __future__ import annotations
import math
from datetime import datetime
from typing import Iterable, Tuple

import pandas as pd
from dateutil import parser as dtparser


# ---------------------------
# Helpers
# ---------------------------

def _parse_date_safe(val) -> datetime | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    # Prefer day-first for bank exports like 11/07/2025
    try:
        return dtparser.parse(s, dayfirst=True, fuzzy=True)
    except Exception:
        return None


def _norm_amount(val) -> float | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val)
    # Remove currency strings and thousand separators
    s = (
        s.replace("BHD", "")
         .replace(",", "")
         .replace("\u00A0", " ")  # non-breaking space
         .strip()
    )
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _within_days(d1: datetime, d2: datetime, days: int) -> bool:
    return abs((d1.date() - d2.date()).days) <= days


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize column headers:
      - strip spaces
      - drop leading '*' or other markers
      - collapse inner double spaces
      - keep original order
    """
    def clean(name: str) -> str:
        n = str(name).strip()
        # remove common leading markers like '*' used in some exports
        while n.startswith(("*", "#", "·", "•")):
            n = n[1:].lstrip()
        # collapse spaces
        n = " ".join(n.split())
        return n
    df = df.copy()
    df.columns = [clean(c) for c in df.columns]
    return df


def _detect_date_column(df: pd.DataFrame) -> str | None:
    """
    Try to find a date column by common names after normalization.
    """
    candidates = {
        "Date",
        "Transaction Date",
        "Posting Date",
        "Value Date",
        "Statement Date",
    }
    # exact match first
    for c in df.columns:
        if c in candidates:
            return c
    # case-insensitive contains
    for c in df.columns:
        cl = c.lower()
        if "date" in cl:
            return c
    return None


def _detect_amount_column(df: pd.DataFrame) -> str | None:
    """
    If there is a single Amount column, return it.
    Otherwise, return None (we'll try Debit/Credit combo).
    """
    # exact name preference
    for name in ["Amount", "Transaction Amount", "Amt"]:
        if name in df.columns:
            return name
    # contains
    for c in df.columns:
        if "amount" in c.lower():
            return c
    return None


def _detect_debit_credit(df: pd.DataFrame) -> tuple[str | None, str | None]:
    """
    Try to find Debit and Credit columns (or Withdrawal/Deposit synonyms).
    Returns (debit_col, credit_col) which may be None if not found.
    """
    debit_names = {"Debit", "Withdrawal", "Withdrawals", "Outflow", "Paid Out", "Money Out"}
    credit_names = {"Credit", "Deposit", "Deposits", "Inflow", "Paid In", "Money In"}

    debit_col = None
    credit_col = None

    # exact matches first
    for c in df.columns:
        if c in debit_names:
            debit_col = c
        if c in credit_names:
            credit_col = c

    # loose contains if not found
    if debit_col is None:
        for c in df.columns:
            cl = c.lower()
            if any(k.lower() in cl for k in ["debit", "withdraw", "outflow", "paid out", "money out"]):
                debit_col = c
                break

    if credit_col is None:
        for c in df.columns:
            cl = c.lower()
            if any(k.lower() in cl for k in ["credit", "deposit", "inflow", "paid in", "money in"]):
                credit_col = c
                break

    return debit_col, credit_col


# ---------------------------
# Public API
# ---------------------------

def match_receipts_to_bank(
    bank_df: pd.DataFrame,
    receipts: Iterable[dict],
    *,
    date_window_days: int = 3,
    amount_tol: float = 0.01,
) -> tuple[pd.DataFrame, dict]:
    """
    Enrich bank_df with receipt matches.

    Auto-detects date & amount columns:
      - If 'Amount' exists, uses that
      - Else if Debit/Credit exist, computes Amount = Credit - Debit (credits positive, debits negative)
    Date parsing is day-first.

    receipts: iterable of dicts with keys:
      - id, amount, date (ISO or human), reference, filename, source
    """

    # Normalize columns like "*Date" -> "Date"
    df = _normalize_columns(bank_df)

    # --- Detect/prepare date column
    bank_date_col = _detect_date_column(df)
    if bank_date_col is None:
        raise KeyError("Could not detect a Date column in the uploaded CSV.")

    # --- Detect/prepare amount column
    bank_amt_col = _detect_amount_column(df)

    if bank_amt_col is None:
        # Fall back to Debit/Credit
        debit_col, credit_col = _detect_debit_credit(df)
        if debit_col is None and credit_col is None:
            # As a last resort, try to find any numeric-looking column named like "Amount (BHD)" etc.
            for c in df.columns:
                if "amount" in c.lower():
                    bank_amt_col = c
                    break

        if bank_amt_col is None and (debit_col is not None or credit_col is not None):
            # Build a synthetic 'Amount' column from debit/credit
            d = df[debit_col] if debit_col in df.columns else 0.0
            c = df[credit_col] if credit_col in df.columns else 0.0
            df["_SynthAmount"] = (c.apply(_norm_amount) if hasattr(c, "apply") else 0.0) - (
                d.apply(_norm_amount) if hasattr(d, "apply") else 0.0
            )
            bank_amt_col = "_SynthAmount"

    if bank_amt_col is None:
        raise KeyError("Could not detect an Amount or Debit/Credit columns in the uploaded CSV.")

    # --- Normalize bank dates & amounts
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

        # Candidate receipts by amount tolerance (absolute compare)
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
        "bank_date_column": bank_date_col,
        "bank_amount_column": bank_amt_col,
    }

    # Clean up temp columns
    df.drop(columns=["_BankDate", "_BankAmt"], inplace=True, errors="ignore")
    return df, summary
