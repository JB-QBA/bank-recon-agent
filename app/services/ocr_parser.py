# app/services/ocr_parser.py

import os
import base64
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Load credentials from service account file (Google Cloud Vision)
CREDENTIALS_FILE = "app/secrets/google-vision-key.json"  # adjust path if needed
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

credentials = service_account.Credentials.from_service_account_file(
    CREDENTIALS_FILE, scopes=SCOPES
)
vision_service = build("vision", "v1", credentials=credentials)


def extract_receipt_data(image_path):
    with open(image_path, "rb") as image_file:
        content = base64.b64encode(image_file.read()).decode("utf-8")

    request_body = {
        "requests": [
            {
                "image": {"content": content},
                "features": [{"type": "TEXT_DETECTION"}],
            }
        ]
    }

    response = vision_service.images().annotate(body=request_body).execute()
    text = response["responses"][0].get("fullTextAnnotation", {}).get("text", "")

    # Dummy extractors for now — refine later
    amount = extract_amount(text)
    date = extract_date(text)
    reference = extract_reference(text)

    return {
        "text": text,
        "amount": amount,
        "date": date,
        "reference": reference,
    }


# Same extractors from before
import re

def extract_amount(text):
    matches = re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d{2})", text)
    return matches[-1] if matches else None

def extract_date(text):
    match = re.search(r"\d{1,2}[-/ ]\w{3,9}[-/ ]\d{2,4}", text, re.IGNORECASE)
    return match.group() if match else None

def extract_reference(text):
    lines = text.splitlines()
    for line in lines:
        if "Ref" in line or "reference" in line.lower():
            return line.strip()
    return None
