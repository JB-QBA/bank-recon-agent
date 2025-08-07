# app/services/ocr_parser.py

import pytesseract
from PIL import Image
import cv2
import re
import platform

# Optional: only override tesseract path if running on Windows
if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_receipt_data(image_path):
    image = cv2.imread(image_path)
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    text = pytesseract.image_to_string(grayscale)

    # Simple extractors — adjust for each format
    amount = extract_amount(text)
    date = extract_date(text)
    reference = extract_reference(text)

    return {
        "text": text,
        "amount": amount,
        "date": date,
        "reference": reference
    }

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
            return line
    return None
