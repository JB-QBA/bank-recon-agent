# bank_reco_agent/app/routes/download.py

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os

router = APIRouter()

EXPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "exports")

@router.get("/download/{filename}")
def download_csv(filename: str):
    file_path = os.path.join(EXPORT_DIR, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=filename, media_type='text/csv')
