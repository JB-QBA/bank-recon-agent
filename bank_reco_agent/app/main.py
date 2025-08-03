# bank_reco_agent/app/main.py

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from app.routes import upload
from app.routes import remittance
from app.routes import download  # ✅ Add this

app = FastAPI(title="Bank Reconciliation Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/upload", tags=["Upload"])
app.include_router(remittance.router, prefix="/upload", tags=["Remittance"])
app.include_router(download.router, tags=["Download"])  # ✅ Mount the download route

@app.get("/")
def root():
    return {"message": "Bank Reconciliation Agent is live."}
