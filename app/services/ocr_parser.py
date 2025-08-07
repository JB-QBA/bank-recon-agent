# app/services/ocr_parser.py

import base64
import json
import os
import re

from google.oauth2 import service_account
from googleapiclient.discovery import build

# 🔐 Load credentials from environment variable (JSON string)
service_account_info = json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
credentials = service_account.Credentials.from_service_account_info(service_account_info)

# Build the Google Vision client
vision_service = build("vision", "v1", credentials=credentials)


def extract_receipt_data(image_path):
    # Load image and encode as base64
    with open(image_path, "rb") as image_file:
        content = base64.b64encode(image_file.read()).decode("utf-8")

    # Call Vision API with TEXT_DETECTION
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

    amount = extract_amount(text)
    date = extract_date(text)
    reference = extract_reference(text)

    return {
        "text": text,
        "amount": amount,
        "date": date,
        "reference": reference
    }


# 🧠 Simple regex-based extractors (tweak if needed)
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
