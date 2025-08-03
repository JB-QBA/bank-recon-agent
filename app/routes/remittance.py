# bank_reco_agent/app/routes/remittance.py

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from typing import List
import simplejson as json

from app.services.remittance_parser import parse_remittance

router = APIRouter()

@router.post("/remittance")
async def upload_remittance(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        parsed = parse_remittance(file_bytes)

        return JSONResponse(content=json.loads(json.dumps({
            "status": "success",
            "filename": file.filename,
            "invoices_found": len(parsed["invoices"]),
            "manual_payments_found": len(parsed["manual_payments"]),
            "data": parsed
        }, ignore_nan=True)))

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse remittance file: {str(e)}")


@router.post("/remittance-multi")
async def upload_multiple_remittance(files: List[UploadFile] = File(...)):
    results = []

    for file in files:
        try:
            content = await file.read()
            parsed = parse_remittance(content)

            results.append({
                "filename": file.filename,
                "invoices_found": len(parsed["invoices"]),
                "manual_payments_found": len(parsed["manual_payments"]),
                "data": parsed
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "error": str(e)
            })

    return JSONResponse(content={"status": "success", "files": results})
