# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import upload
from app.routes import remittance
from app.routes import download
from app.routes import xero_auth
from app.routes import xero_data
from app.routes import ocr_receipt
from app.routes import recon_receipts  # ✅ NEW

app = FastAPI(title="Bank Reconciliation Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔗 Include all route modules
app.include_router(upload.router, prefix="/upload", tags=["Upload"])
app.include_router(remittance.router, prefix="/upload", tags=["Remittance"])
app.include_router(download.router, tags=["Download"])
app.include_router(xero_auth.router, tags=["Xero Auth"])
app.include_router(xero_data.router, tags=["Xero API"])
app.include_router(ocr_receipt.router)                 # Receipt OCR
app.include_router(recon_receipts.router)              # ✅ Reconciliation: receipt matching

@app.get("/")
def root():
    return {"message": "Bank Reconciliation Agent is live."}
