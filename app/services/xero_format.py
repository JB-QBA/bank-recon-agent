# bank_reco_agent/app/services/xero_format.py

import pandas as pd
import os
from datetime import datetime

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "../templates/statement_template.csv")

def to_xero_format(transactions: list, output_path: str = None) -> pd.DataFrame:
    """
    Loads the Xero import template, fills it with transaction data, and outputs the file.
    Ensures all dates are normalized to yyyy/mm/dd format.
    """
    if not transactions:
        raise ValueError("No transactions provided")

    # Load template header (column names only)
    try:
        template = pd.read_csv(TEMPLATE_PATH, nrows=0)
        required_cols = template.columns.tolist()
    except Exception as e:
        raise ValueError(f"Could not load template from {TEMPLATE_PATH}: {str(e)}")

    # Prepare data from parsed transaction list
    df = pd.DataFrame(transactions)

    # Normalize date to yyyy/mm/dd format regardless of input
    df["*Date"] = pd.to_datetime(
        df["date"], errors="coerce", dayfirst=True
    ).dt.strftime("%Y/%m/%d")

    # Rename and align remaining columns
    rename_map = {
        "amount": "*Amount",
        "description": "Description"
    }
    df.rename(columns=rename_map, inplace=True)

    # Drop source date column if present
    if "date" in df.columns:
        df.drop(columns=["date"], inplace=True)

    # Keep only columns required by template
    df = df[[col for col in required_cols if col in df.columns]]

    # Fill any missing columns from template
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""

    df = df[required_cols]  # enforce column order

    # Write to CSV if output path is provided
    if output_path:
        df.to_csv(output_path, index=False)

    return df
