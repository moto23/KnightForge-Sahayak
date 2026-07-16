"""
OCR infrastructure adapters (Phase 7).

Concrete implementations of the domain's OCR-related ports:

    TesseractOCRProvider  — OCRProvider backed by the Tesseract engine
    PyMuPdfInspector      — DocumentInspector backed by PyMuPDF + Pillow

Nothing outside this package imports pytesseract, fitz (PyMuPDF), or PIL.
"""
