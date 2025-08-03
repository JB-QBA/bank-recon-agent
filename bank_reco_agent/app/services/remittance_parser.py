# bank_reco_agent/app/services/remittance_parser.py

import pandas as pd

def parse_remittance(file_bytes: bytes) -> dict:
    xls = pd.ExcelFile(file_bytes)

    invoices = []
    manual_payments = []

    # --- SHEET 1: Invoices ---
    if "Aged Payables Detail" in xls.sheet_names:
        df = xls.parse("Aged Payables Detail", skiprows=4)
        current_supplier = None

        for _, row in df.iterrows():
            if pd.notna(row.iloc[0]) and pd.isna(row.iloc[1]):
                current_supplier = str(row.iloc[0])
                continue

            if pd.isna(row.get("Invoice Reference")) or pd.isna(row.get("Total")):
                continue

            # Safe date formatting
            invoice_date = pd.to_datetime(row.get("Invoice Date"), errors="coerce")
            due_date = pd.to_datetime(row.get("Due Date"), errors="coerce")

            invoice_data = {
                "supplier": current_supplier,
                "invoice_number": str(row.get("Invoice Reference")),
                "invoice_date": invoice_date.strftime("%Y-%m-%d") if pd.notna(invoice_date) else None,
                "due_date": due_date.strftime("%Y-%m-%d") if pd.notna(due_date) else None,
                "amount": float(row.get("Total", 0))
            }
            invoices.append(invoice_data)

    # --- SHEET 2: Manual Payments ---
    if "Manual Payments" in xls.sheet_names:
        df_manual = xls.parse("Manual Payments")

        for _, row in df_manual.iterrows():
            if pd.isna(row.get("Date")) or pd.isna(row.get("Amount")):
                continue

            payment_date = pd.to_datetime(row.get("Date"), errors="coerce")
            payment_data = {
                "date": payment_date.strftime("%Y-%m-%d") if pd.notna(payment_date) else None,
                "payee": str(row.get("Employee/Supplier", "")).strip(),
                "amount": float(row.get("Amount", 0)),
                "allocation": str(row.get("Description/Account", "")) if pd.notna(row.get("Description/Account")) else "",
                "notes": str(row.get("Notes", "")) if pd.notna(row.get("Notes")) else ""
            }
            manual_payments.append(payment_data)

    return {
        "invoices": invoices,
        "manual_payments": manual_payments
    }
