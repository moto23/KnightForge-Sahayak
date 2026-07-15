"""
Infrastructure layer — concrete adapters for the domain's ports.

Anything that touches the outside world (storage today; OCR, OpenAI, and PDF
engines in later phases) lives under this package, keeping domain and services
pure and swappable.
"""
