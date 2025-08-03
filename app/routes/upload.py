# bank_reco_agent/app/routes/upload.py

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from app.services import parser
from app.services.xero_format import to_xero_format
from typing import List
from datetime import datetime
import os
import simplejson as json

router = APIRouter()

EXPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)

@router.post("/bank-statement")
async def upload_bank_statement(files: List[UploadFile] = File(...)):
    results = []

    for file in files:
        try:
            content = await file.read()
            parsed = parser.extract_transactions(file.filename, content)

            # Detect bank type from filename
            fname = file.filename.lower()
            if "nbb" in fname:
                bank_code = "NBB"
            elif "kfh" in fname and "card" in fname:
                bank_code = "KFH_CC"
            elif "kfh" in fname and "account" in fname:
                bank_code = "KFH"
            else:
                bank_code = "GEN"

            today_str = datetime.now().strftime("%Y%m%d")
            export_filename = f"{bank_code}{today_str}.csv"
            export_path = os.path.join(EXPORT_DIR, export_filename)

            # Export using your statement_template.csv logic
            to_xero_format(parsed, export_path)

            results.append({
                "filename": file.filename,
                "record_count": len(parsed),
                "download_url": f"/download/{export_filename}",
                "status": "parsed"
            })

        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to process {file.filename}: {str(e)}")

    return JSONResponse(content=json.loads(json.dumps({
        "status": "success",
        "results": results
    }, ignore_nan=True)))
