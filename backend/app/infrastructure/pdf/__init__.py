"""
PDF-generation infrastructure adapters (Phase 8).

Concrete implementation of the domain's PDFGenerator port:

    CoordinateOverlayPDFGenerator — overlays text/checkmarks onto the original
    template with PyMuPDF, preserving layout, fonts, and spacing.

Nothing outside this package imports a PDF-writing library for generation.
"""
