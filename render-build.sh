#!/usr/bin/env bash

echo "🔥 Starting custom build script..."

# Install tesseract-ocr before app build
apt-get update
apt-get install -y tesseract-ocr

# Now install Python dependencies
pip install -r requirements.txt
