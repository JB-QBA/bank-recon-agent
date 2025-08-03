# bank_reco_agent/app/services/parser.py

import pandas as pd
import io
import re

def extract_transactions(filename: str, file_bytes: bytes):
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        return parse_excel(file_bytes, filename)
    elif filename.endswith(".csv"):
        return parse_csv(file_bytes, filename)
    elif filename.endswith(".pdf"):
        return parse_pdf(file_bytes)
    elif filename.endswith(".ofx"):
        return parse_ofx_passthrough(file_bytes)
    else:
        raise ValueError("Unsupported file type. Supported: .xlsx, .xls, .csv, .pdf, .ofx")

# --- Entry Routing ---

def parse_excel(file_bytes: bytes, filename: str):
    df = pd.read_excel(io.BytesIO(file_bytes), header=None)
    return route_bank_parser(filename, df)

def parse_csv(file_bytes: bytes, filename: str):
    df = pd.read_csv(io.BytesIO(file_bytes), header=None)
    return route_bank_parser(filename, df)

def route_bank_parser(filename: str, df_raw: pd.DataFrame):
    filename = filename.lower()

    if "nbb" in filename:
        return parse_nbb(df_raw)
    elif "kfh" in filename and "account" in filename:
        return parse_kfh_account(df_raw)
    elif "kfh" in filename and "card" in filename:
        return parse_kfh_card(df_raw)
    elif "kfh" in filename and "business" in filename:
        return parse_kfh_business(df_raw)
    else:
        raise ValueError("Bank format not yet supported for filename: " + filename)

# --- Shared Helpers ---

def clean_currency(value):
    if pd.isnull(value) or str(value).strip() == "":
        return None
    return float(re.sub(r"[^\d.-]", "", str(value).replace(",", "").strip()))

def determine_signed_amount(row, sign_col, amount_col):
    sign = -1 if pd.notnull(row.get(sign_col)) else 1
    value = clean_currency(row.get(amount_col))
    return sign * abs(value) if value is not None else None

def detect_header_row(df_raw: pd.DataFrame, keywords: list):
    for idx, row in df_raw.iterrows():
        cleaned_cells = [str(cell).lower().strip().replace('\n', ' ') for cell in row if pd.notnull(cell)]
        if len(cleaned_cells) == 0:
            continue
        match_count = sum(
            any(keyword in cell for cell in cleaned_cells)
            for keyword in keywords
        )
        if match_count >= 2:
            return idx
    return None

def normalize_headers(df):
    renamed_cols = {}
    for col in df.columns:
        col_lower = str(col).lower()
        if "date" in col_lower:
            renamed_cols[col] = "date"
        elif "description" in col_lower or "details" in col_lower:
            renamed_cols[col] = "description"
        elif "debit" in col_lower:
            renamed_cols[col] = "debit"
        elif "credit" in col_lower:
            renamed_cols[col] = "credit"
        elif "bhd" in col_lower:
            renamed_cols[col] = "bhd"
    df.rename(columns=renamed_cols, inplace=True)
    return df

# --- Bank-specific Parsers ---

def parse_nbb(df_raw: pd.DataFrame):
    header_idx = detect_header_row(df_raw, ["transaction", "date", "description", "debit", "credit"])
    if header_idx is None:
        raise ValueError("Unable to locate header row for NBB file.")

    df_raw.columns = df_raw.iloc[header_idx]
    df = df_raw[(header_idx + 1):].reset_index(drop=True)
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = normalize_headers(df)

    df["debit"] = df.get("debit", None).apply(clean_currency)
    df["credit"] = df.get("credit", None).apply(clean_currency)

    df["amount"] = df.apply(
        lambda row: -abs(row["debit"]) if pd.notnull(row.get("debit")) else abs(row["credit"]) if pd.notnull(row.get("credit")) else None,
        axis=1
    )

    df = df[["date", "description", "amount"]]
    df.dropna(subset=["date", "amount"], inplace=True)
    return df.head(100).to_dict(orient="records")

def parse_kfh_account(df_raw: pd.DataFrame):
    header_idx = detect_header_row(df_raw, ["date", "description", "debit", "credit"])
    if header_idx is None:
        raise ValueError("Unable to locate header row for KFH Account file.")

    df_raw.columns = df_raw.iloc[header_idx]
    df = df_raw[(header_idx + 1):].reset_index(drop=True)
    df.columns = [str(c).strip().lower() for c in df.columns]

    df.rename(columns={
        "date التاريخ": "date",
        "description التفاصيل": "description",
        "credits المدينين": "credit",
        "debits الدائنين": "debit"
    }, inplace=True)

    df["debit"] = df.get("debit", None).apply(clean_currency)
    df["credit"] = df.get("credit", None).apply(clean_currency)

    df["amount"] = df.apply(
        lambda row: -abs(row["debit"]) if pd.notnull(row.get("debit")) else abs(row["credit"]) if pd.notnull(row.get("credit")) else None,
        axis=1
    )

    df = df[["date", "description", "amount"]]
    df.dropna(subset=["date", "amount"], inplace=True)
    return df.head(100).to_dict(orient="records")

def parse_kfh_card(df_raw: pd.DataFrame):
    header_idx = detect_header_row(df_raw, ["transaction", "date", "details", "debit", "credit", "bhd"])
    if header_idx is None:
        raise ValueError("Unable to locate header row for KFH Card file.")

    df_raw.columns = df_raw.iloc[header_idx]
    df = df_raw[(header_idx + 1):].reset_index(drop=True)
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = normalize_headers(df)

    if "date" not in df.columns or "description" not in df.columns:
        raise ValueError(f"Expected columns not found. Available columns: {list(df.columns)}")

    df["amount"] = df.apply(lambda row: determine_signed_amount(row, "debit", "bhd"), axis=1)

    df = df[["date", "description", "amount"]]
    df.dropna(subset=["date", "amount"], inplace=True)
    return df.head(100).to_dict(orient="records")

def parse_kfh_business(df_raw: pd.DataFrame):
    header = df_raw.iloc[0].tolist()
    df = df_raw[1:].copy()
    df.columns = header

    df.rename(columns=lambda x: str(x).strip().lower(), inplace=True)
    df.rename(columns={
        'date': 'date',
        'description': 'description',
        'debit': 'debit',
        'credit': 'credit'
    }, inplace=True)

    df['description'] = df['description'].astype(str).str.replace(r'<br\s*/?>', ' | ', regex=True)

    def clean_currency(val):
        try:
            return float(str(val).replace(',', '').strip())
        except:
            return None

    df['debit'] = df['debit'].apply(clean_currency)
    df['credit'] = df['credit'].apply(clean_currency)

    df['amount'] = df.apply(
        lambda row: -abs(row['debit']) if pd.notnull(row['debit']) else abs(row['credit']) if pd.notnull(row['credit']) else None,
        axis=1
    )

    df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
    df = df[['date', 'description', 'amount']]
    df.dropna(subset=['date', 'amount'], inplace=True)

    return df.to_dict(orient="records")

# --- Other file types ---

def parse_pdf(file_bytes: bytes):
    text_preview = file_bytes[:2000].decode(errors='ignore')
    return {"preview_text": text_preview[:1000]}

def parse_ofx_passthrough(file_bytes: bytes):
    return {"message": "OFX file upload accepted (no parsing needed)."}
