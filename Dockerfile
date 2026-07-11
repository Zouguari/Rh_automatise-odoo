FROM odoo:17.0

USER root

# Install system dependencies for OCR and PDF image conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fra \
    poppler-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies for CV text extraction
# Pin cryptography and pyOpenSSL to ensure full compatibility with urllib3 in Odoo 17
RUN pip install --no-cache-dir -U \
    "cryptography==38.0.4" \
    "pyOpenSSL<23.0.0" \
    pdfplumber \
    python-docx \
    pytesseract \
    pdf2image

USER odoo
