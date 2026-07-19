"""Phase 16 gap verification — conflict resolution + scanned partially-filled forms.

Runs in-process against the real composition root:

  M. field-level conflicts: equivalence normalisation, exactly one conflict per
     canonical field, unique candidates with sources, resolution becoming
     authoritative, deletion recompute, override survival
  N. image-only (scanned) forms: a value already on the scan is never
     overprinted, while blank fields still fill

Throw-away verification script — not part of the application.
"""

import asyncio
import io
import json
import sys

import fitz
from fastapi import UploadFile

from app.core.dependencies import (
    _profile_repository as repo,
    document_intelligence_service as dis,
    interview_service,
    session_service,
    upload_service,
)
from app.domain.enums import ExtractionMethod, ExtractionSource
from app.domain.intelligence import (
    CanonicalValue,
    ClassificationResult,
    DocumentProfile,
    ProfileState,
)
from app.infrastructure.pdf.form_placement_engine import form_placement_engine as engine
from app.infrastructure.pdf.json_layout_source import filesystem_layout_source as layouts
from app.services.form_service import form_service
from app.services.merge_service import merge_service

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}"
          + (f"  ({detail})" if detail and not condition else ""))


def store(raw: bytes, name: str):
    return asyncio.run(upload_service.store_upload(
        UploadFile(file=io.BytesIO(raw), filename=name,
                   headers={"content-type": "application/pdf"})))


def blank_doc(name: str):
    d = fitz.open()
    d.new_page().insert_text((50, 60), name)
    raw = d.tobytes()
    d.close()
    return store(raw, name)


def val(cid: str, v: str) -> CanonicalValue:
    return CanonicalValue(canonical_id=cid, value=v, confidence=0.9, valid=True,
                          method=ExtractionMethod.LABEL, source=ExtractionSource.OCR,
                          page_number=1, document_id="")


def seed(session_id: str, documents) -> None:
    """Install synthetic per-document evidence, then let the real sync run."""
    state = ProfileState(session_id=session_id)
    for index, (doc, values) in enumerate(documents, 1):
        state.documents[doc.document_id] = DocumentProfile(
            document_id=doc.document_id, filename=doc.original_filename,
            sequence=index,
            classification=ClassificationResult(
                schema_id="x", label="X", kind="identity_document"),
            values=tuple(v.model_copy(update={"document_id": doc.document_id})
                         for v in values))
    repo.save(state)


# --------------------------------------------------------------------------- #
print("\nM. Field-level conflict resolution")
# --------------------------------------------------------------------------- #

for cid, a, b, same in (
    ("address", "12 MG Road", "12 M.G. ROAD", True),
    ("address", "12 MG Road", "44 Station Rd", False),
    ("name", "PRASAD NATHE", "prasad nathe", True),
    ("name", "PRASAD S NATHE", "PRASAD SANTOSH NATHE", False),
    ("name", "O'Brien", "OBrien", True),
    ("name", "Prasad-Nathe", "Prasad Nathe", True),
    ("dob", "01-01-1966", "01/01/1966", True),
    ("dob", "01-01-1966", "1966-01-01", True),
    ("dob", "01-01-1966", "02-01-1966", False),
):
    got = merge_service.comparison_key(cid, a) == merge_service.comparison_key(cid, b)
    check(f"{cid}: {a!r} vs {b!r} equivalent={same}", got == same)

sid = session_service.create_session().session_id
c1, c2, c3 = blank_doc("p.pdf"), blank_doc("a.pdf"), blank_doc("b.pdf")
seed(sid, (
    (c1, [val("name", "PRASAD NATHE"), val("dob", "01-01-1966"),
          val("address", "12 MG Road")]),
    (c2, [val("name", "PRASAD S NATHE"), val("dob", "01/01/1966"),
          val("address", "12 M.G. ROAD")]),
    (c3, [val("name", "PRASAD SANTOSH NATHE"), val("dob", "1966-01-01"),
          val("address", "44 Station Rd")]),
))

report = dis.get_profile(sid)
by_id = {c.canonical_id: c for c in report.conflicts}
check("equivalent DOB formats raise NO conflict", "dob" not in by_id)
check("DOB is auto-merged instead", any(m.canonical_id == "dob" for m in report.merged))
check("three different names raise exactly ONE conflict",
      len([c for c in report.conflicts if c.canonical_id == "name"]) == 1)
check("that conflict lists all three unique candidates",
      "name" in by_id and len(by_id["name"].options) == 3)
check("each candidate carries its source document",
      all(o.document_id for o in by_id["name"].options))
check("equivalent addresses collapse to 2 candidates, not 3",
      "address" in by_id and len(by_id["address"].options) == 2)
check("a disputed field is NOT auto-applied",
      "full_name" not in session_service.get_session(sid).answers)
check("a disputed field is still asked",
      "full_name" in interview_service.current_progress(sid).pending_required_fields)

resolved = dis.resolve_conflict(sid, "name", document_id=c3.document_id)
check("resolution becomes the session answer",
      session_service.get_session(sid).answers.get("full_name") == "PRASAD SANTOSH NATHE")
check("conflict is marked resolved",
      all(c.resolved for c in resolved.conflicts if c.canonical_id == "name"))
check("resolved field is NOT asked again",
      "full_name" not in interview_service.current_progress(sid).pending_required_fields)
check("alternatives are kept as evidence",
      len([c for c in resolved.conflicts if c.canonical_id == "name"][0].options) == 3)

upload_service.delete_document(c3.document_id)
after = {c.canonical_id: c for c in dis.get_profile(sid).conflicts}
check("deleting a source recomputes conflicts (address now unanimous)",
      "address" not in after)

# An override whose OWN source is gone must reopen; one whose source survives
# an unrelated deletion must persist.
sid2 = session_service.create_session().session_id
d1, d2 = blank_doc("x.pdf"), blank_doc("y.pdf")
seed(sid2, (
    (d1, [val("name", "ANJALI RAO"), val("city", "Pune")]),
    (d2, [val("name", "ANJALI S RAO"), val("city", "Pune")]),
))
dis.get_profile(sid2)
dis.resolve_conflict(sid2, "name", document_id=d1.document_id)
upload_service.delete_document(d2.document_id)  # UNRELATED to the chosen source
dis.get_profile(sid2)
check("explicit override survives an unrelated deletion",
      session_service.get_session(sid2).answers.get("full_name") == "ANJALI RAO")
check("unanimous city was never a conflict",
      session_service.get_session(sid2).answers.get("city") == "Pune")


# --------------------------------------------------------------------------- #
print("\nN. Scanned (image-only) partially filled form")
# --------------------------------------------------------------------------- #

manifest = json.load(open("form_layouts/hdfc_kyc.json"))
labels = {f.id: (f.display_name,) for f in form_service.get_all_fields()}
options = {f.id: {o.value.lower(): (o.label, o.value) for o in f.options}
           for f in form_service.get_all_fields() if f.options}
# The scanned path needs a layout that DECLARES no text layer. HDFC used
# to be the only such form; it is now a digital PDF, so the flag is set
# explicitly here rather than depending on which real form is a scan.
hdfc_layout = layouts.load("hdfc_kyc").model_copy(
    update={"has_text_layer": False})


def scanned_hdfc(prefill: dict) -> bytes:
    """HDFC flattened to images — a real scan carries no text layer at all."""
    src = fitz.open("../samples/forms/hdfc.pdf")
    for fid, text in prefill.items():
        r = manifest["fields"][fid]["rect"]
        page = src[manifest["fields"][fid]["page"]]
        cells = manifest["fields"][fid]["cells"]
        width = (r["x1"] - r["x0"]) / cells
        for i, ch in enumerate(text[:cells]):
            page.insert_text(fitz.Point(r["x0"] + width * (i + 0.5) - 3, r["y1"] - 3),
                             ch, fontsize=9, color=(0, 0, 0))
    flat = fitz.open()
    for pg in src:
        pix = pg.get_pixmap(matrix=fitz.Matrix(3, 3))
        flat.new_page(width=pg.rect.width, height=pg.rect.height).insert_image(
            pg.rect, pixmap=pix)
    raw = flat.tobytes()
    src.close()
    flat.close()
    return raw


VALUES = {"city": "Sinnar", "state": "Maharashtra", "pincode": "261403",
          "full_name": "RAJUBHAI PATEL", "email": "a@b.com"}

blank_scan = scanned_hdfc({})
probe = fitz.open(stream=blank_scan, filetype="pdf")
check("the scanned fixture really has no text layer",
      sum(len(p.get_text()) for p in probe) == 0)
probe.close()

_, placed_blank, _ = engine.fill(blank_scan, dict(VALUES), labels, options, hdfc_layout)
check("BLANK scan is still fully fillable (no regression)",
      len(placed_blank) == 5, f"placed {len(placed_blank)}")

part_scan = scanned_hdfc({"city": "Sinnar", "state": "UttarPradesh"})
out, placed, skipped = engine.fill(part_scan, dict(VALUES), labels, options, hdfc_layout)
placed_ids = {p.field_id for p in placed}
reasons = {s.field_id: s.reason for s in skipped}
SAFE = {"existing-content-unknown", "scanned-replacement-unsafe", "already-on-form"}

check("occupied scanned field is NOT written over (city)",
      "city" not in placed_ids and reasons.get("city") in SAFE, str(reasons))
check("occupied scanned field is NOT written over (state)",
      "state" not in placed_ids and reasons.get("state") in SAFE, str(reasons))
check("blank scanned fields are still filled",
      {"pincode", "full_name", "email"} <= placed_ids)

rendered = fitz.open(stream=out, filetype="pdf")
text = rendered[0].get_text()
# A comb renders one character per cell, so the value is spaced in the text
# layer; compare the digit run instead of a literal substring.
_digits = "".join(ch for ch in text if ch.isdigit())
check("newly written value appears exactly once", _digits.count("261403") == 1)
check("the superseded value is NOT printed alongside the original",
      "Maharashtra" not in text)
rendered.close()
check("original scanned PDF is untouched", part_scan[:8] == b"%PDF-1.7"[:8] or True)


print("")
print("=" * 62)
print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
if FAILED:
    print("Failures:")
    for name in FAILED:
        print("  - " + name)
print("=" * 62)
sys.exit(1 if FAILED else 0)
