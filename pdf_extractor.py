"""Extract text and basic metadata from PDF invoices using PyMuPDF."""

import fitz  # PyMuPDF


def extract_text_from_pdf(file_path: str) -> str:
    """Return all text found in the PDF (concatenated across pages)."""
    text_parts = []
    with fitz.open(file_path) as doc:
        for page in doc:
            text_parts.append(page.get_text())
    return "\n---PAGE_BREAK---\n".join(text_parts)
