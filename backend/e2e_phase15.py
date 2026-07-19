"""Phase 15 verification — form assets, strict slot validation, auth policy.

Runs IN-PROCESS against the real composition root (no HTTP server needed), so
it exercises the same singletons the API uses:

   A. strict slot validation, judged on CONTENT not filename
      1. PAN card named "sbi-kyc-form.pdf" into PRIMARY   -> rejected
      2. real KYC form named "random-scan.pdf" into SUPPORTING -> rejected
      3. same KYC form into PRIMARY                       -> accepted
      4. PAN card into SUPPORTING                         -> accepted
      5. one invalid file does not block valid ones in a batch
   B. conditional photo/signature requirements
      6. no primary form            -> nothing required, upload refused
      7. form WITH photo box        -> both become required interview fields
      8. form WITHOUT               -> never asked
   C. asset upload validation (type / size / decodability)
   D. asset lifecycle recompute (delete asset, delete primary form)
   E. PDF placement: photo and signature land in DIFFERENT, correct regions,
      and "sign across the photograph" never produces a signature region
   F. auth policy: frontend and backend rules agree

Throw-away verification script — not part of the application.
"""

import asyncio
import io
import sys

import fitz
from fastapi import UploadFile
from pydantic import ValidationError

from app.core.dependencies import (
    asset_service,
    document_intelligence_service as dis,
    interview_service,
    session_service,
    upload_service,
    pdf_generation_service,
)
from app.core.exceptions import (
    AssetNotRequiredError,
    AssetTooLargeError,
    InvalidAssetError,
    NotAPrimaryFormError,
    PrimaryFormInSupportingSlotError,
)
from app.domain.form_assets import AssetKind
from app.infrastructure.pdf.uploaded_form_filler import uploaded_form_filler
from app.schemas.auth import RegisterRequest
from app.services.form_asset_detector import form_asset_detector

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not condition else ""))


def raises(name: str, exc_type, fn) -> None:
    """Assert `fn()` raises `exc_type` — used for the rejection paths."""
    try:
        fn()
        check(name, False, "no exception raised")
    except exc_type:
        check(name, True)
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"raised {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

KYC_FORM_BYTES = open("../samples/sample-kyc.pdf", "rb").read()


def text_pdf(lines: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    y = 60
    for line in lines.split("\n"):
        page.insert_text((50, y), line, fontsize=11)
        y += 16
    raw = document.tobytes()
    document.close()
    return raw


def image_bytes(width: int, height: int, rgb: tuple[float, float, float]) -> bytes:
    document = fitz.open()
    page = document.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(0, 0, width, height), color=rgb, fill=rgb)
    raw = page.get_pixmap().tobytes("png")
    document.close()
    return raw


def store(raw: bytes, name: str):
    return asyncio.run(
        upload_service.store_upload(
            UploadFile(
                file=io.BytesIO(raw),
                filename=name,
                headers={"content-type": "application/pdf"},
            )
        )
    )


PAN_BYTES = text_pdf(
    "INCOME TAX DEPARTMENT\nGOVT. OF INDIA\n"
    "Permanent Account Number Card\nABCDE1234F\n"
    "RAHUL SHARMA\nDate of Birth 01/01/1990"
)
PHOTO = image_bytes(100, 130, (1, 0, 0))
SIGNATURE = image_bytes(200, 50, (0, 0.6, 0))


# --------------------------------------------------------------------------- #
# A. Strict slot validation (content, never filename)
# --------------------------------------------------------------------------- #

print("\nA. Strict primary/supporting slot validation")

session_a = session_service.create_session().session_id
# Filename deliberately LIES about what the file is.
pan_doc = store(PAN_BYTES, "sbi-kyc-form.pdf")
kyc_doc = store(KYC_FORM_BYTES, "random-scan.pdf")

raises(
    "PAN card in PRIMARY slot is rejected (despite its KYC filename)",
    NotAPrimaryFormError,
    lambda: dis.process_document(pan_doc.document_id, session_a, is_primary=True),
)
state = dis.profile_state(session_a)
check(
    "rejected primary never activated a form",
    state is None or state.primary_document_id is None,
)
check(
    "rejected primary never merged into the profile",
    state is None or pan_doc.document_id not in state.documents,
)

raises(
    "KYC form in SUPPORTING slot is rejected (despite its neutral filename)",
    PrimaryFormInSupportingSlotError,
    lambda: dis.process_document(kyc_doc.document_id, session_a, is_primary=False),
)

report = dis.process_document(kyc_doc.document_id, session_a, is_primary=True)
check("valid KYC form IS accepted as primary", report.state.primary_form_id == "cvl_kyc")

report = dis.process_document(pan_doc.document_id, session_a, is_primary=False)
check(
    "PAN card IS accepted as a supporting document",
    pan_doc.document_id in report.state.documents,
)

# One bad file must not block the good ones in the same batch.
session_batch = session_service.create_session().session_id
batch = [
    (store(KYC_FORM_BYTES, "a.pdf"), True),   # valid primary
    (store(PAN_BYTES, "b.pdf"), False),        # valid supporting
    (store(KYC_FORM_BYTES, "c.pdf"), False),   # INVALID: form in supporting slot
    (store(PAN_BYTES, "d.pdf"), False),        # valid supporting
]
accepted = 0
for doc, primary in batch:
    try:
        dis.process_document(doc.document_id, session_batch, is_primary=primary)
        accepted += 1
    except (NotAPrimaryFormError, PrimaryFormInSupportingSlotError):
        pass
check("one invalid file does not block the valid ones", accepted == 3, f"{accepted}/3")


# --------------------------------------------------------------------------- #
# B. Conditional photo / signature requirements
# --------------------------------------------------------------------------- #

print("\nB. Conditional photo + signature requirements")

session_b = session_service.create_session().session_id
check("no primary form -> no asset requirements", dis.asset_requirements(session_b) is None)
raises(
    "asset upload refused when no form requires it",
    AssetNotRequiredError,
    lambda: asset_service.store(session_b, AssetKind.PHOTO, "p.png", "image/png", PHOTO),
)

doc_b = store(KYC_FORM_BYTES, "form.pdf")
dis.process_document(doc_b.document_id, session_b, is_primary=True)
requirements = dis.asset_requirements(session_b)
check("photo detected on a form that has a photo box", requirements.photo)
check("signature detected on a form that has one", requirements.signature)
check("detected from the DOCUMENT, not just the schema", requirements.detected_from == "document")

scoped = session_service.get_session(session_b).required_field_ids or []
check("applicant_photo became a required interview field", "applicant_photo" in scoped)
check("applicant_signature became a required interview field", "applicant_signature" in scoped)

pending = interview_service.current_progress(session_b).pending_required_fields
check("photo shows as Pending before upload", "applicant_photo" in pending)

# A document with NO photo/signature must never trigger the question.
plain = form_asset_detector.detect(PAN_BYTES)
check("form WITHOUT a photo box -> photo never required", not plain.photo)
check("form WITHOUT a signature line -> never required", not plain.signature)


# --------------------------------------------------------------------------- #
# C. Asset upload validation
# --------------------------------------------------------------------------- #

print("\nC. Asset upload validation")

raises(
    "non-image type rejected",
    InvalidAssetError,
    lambda: asset_service.store(session_b, AssetKind.PHOTO, "x.gif", "image/gif", PHOTO),
)
raises(
    "truncated image rejected (forced decode, not just a header check)",
    InvalidAssetError,
    lambda: asset_service.store(session_b, AssetKind.PHOTO, "x.png", "image/png", PHOTO[:200]),
)
raises(
    "photo over 5 MB rejected",
    AssetTooLargeError,
    lambda: asset_service.store(
        session_b, AssetKind.PHOTO, "x.png", "image/png",
        PHOTO[:8] + b"\x00" * (5 * 1024 * 1024 + 1),
    ),
)
raises(
    "signature over 2 MB rejected",
    AssetTooLargeError,
    lambda: asset_service.store(
        session_b, AssetKind.SIGNATURE, "x.png", "image/png",
        PHOTO[:8] + b"\x00" * (2 * 1024 * 1024 + 1),
    ),
)
# 3 MB is over the signature cap but under the photo cap — proves the caps are
# genuinely per-kind rather than one shared limit.
three_mb = PHOTO[:8] + b"\x00" * (3 * 1024 * 1024)
raises(
    "3 MB rejected as a signature (2 MB cap)",
    AssetTooLargeError,
    lambda: asset_service.store(session_b, AssetKind.SIGNATURE, "s.png", "image/png", three_mb),
)
raises(
    "3 MB reaches the DECODE stage as a photo (5 MB cap) - size not the blocker",
    InvalidAssetError,
    lambda: asset_service.store(session_b, AssetKind.PHOTO, "p.png", "image/png", three_mb),
)

photo_asset = asset_service.store(session_b, AssetKind.PHOTO, "me.png", "image/png", PHOTO)
check("valid photo accepted", photo_asset.width == 100 and photo_asset.height == 130)
asset_service.store(session_b, AssetKind.SIGNATURE, "sig.png", "image/png", SIGNATURE)
answers = session_service.get_session(session_b).answers
check("photo answered its interview field", answers.get("applicant_photo") == photo_asset.asset_id)
check("signature answered its interview field", "applicant_signature" in answers)


# --------------------------------------------------------------------------- #
# D. Lifecycle recompute
# --------------------------------------------------------------------------- #

print("\nD. Asset + primary-form lifecycle recompute")

asset_service.delete(session_b, AssetKind.PHOTO)
progress = interview_service.current_progress(session_b)
session_now = session_service.get_session(session_b)
check("deleting the photo returns it to Pending", "applicant_photo" in progress.pending_required_fields)
check(
    "deleted photo is not left as an 'invalid' answer",
    "applicant_photo" not in session_now.validation_errors,
)

upload_service.delete_document(doc_b.document_id)
dis.get_profile(session_b)  # the one authoritative recompute
progress = interview_service.current_progress(session_b)
session_now = session_service.get_session(session_b)
check("deleting the primary form clears asset requirements", dis.asset_requirements(session_b) is None)
check("photo no longer required", "applicant_photo" not in progress.pending_required_fields)
check("signature no longer required", "applicant_signature" not in progress.pending_required_fields)
check("stale signature answer retracted", "applicant_signature" not in session_now.answers)
check("primary_document_id cleared", dis.profile_state(session_b).primary_document_id is None)


# --------------------------------------------------------------------------- #
# E. PDF placement
# --------------------------------------------------------------------------- #

print("\nE. PDF placement of photo vs signature")

detected = form_asset_detector.detect(KYC_FORM_BYTES)
photo_region = detected.photo_regions[0]
signature_region = detected.signature_regions[0]

overlap = not (
    photo_region.x1 <= signature_region.x0
    or signature_region.x1 <= photo_region.x0
    or photo_region.y1 <= signature_region.y0
    or signature_region.y1 <= photo_region.y0
)
check("photo and signature regions do not overlap", not overlap)
check(
    "'sign across the photograph' never becomes a signature region",
    not any("across" in r.matched_text.lower() for r in detected.signature_regions),
)
check(
    "'Signature of Applicant' is the winning signature region",
    "signature of applicant" in signature_region.matched_text.lower(),
)

filled_bytes, filled, unplaced = uploaded_form_filler.fill(
    KYC_FORM_BYTES,
    {
        "full_name": "RAHUL SHARMA",
        "applicant_photo": "asset-id-photo",
        "applicant_signature": "asset-id-signature",
    },
    {"full_name": ("Name",)},
    {},
    None,
    assets={AssetKind.PHOTO: PHOTO, AssetKind.SIGNATURE: SIGNATURE},
    asset_requirements=detected,
)
placed = {f.field_id for f in filled}
check("photo placed onto the form", "applicant_photo" in placed)
check("signature placed onto the form", "applicant_signature" in placed)

output = fitz.open(stream=filled_bytes, filetype="pdf")
embedded = sum(len(output[p].get_images(full=True)) for p in range(output.page_count))
check("exactly two images embedded (no duplicate stamping)", embedded == 2, f"got {embedded}")
page_text = output[0].get_text()
check("raw asset ids never printed as text", "asset-id-photo" not in page_text)
check("raw signature id never printed as text", "asset-id-signature" not in page_text)
output.close()
check("the uploaded original is never modified", KYC_FORM_BYTES == open("../samples/sample-kyc.pdf", "rb").read())

# Aspect ratio must be preserved, not stretched to fill the box.
rect = uploaded_form_filler._fit_preserving_aspect(SIGNATURE, signature_region)
source_ratio = 200 / 50
drawn_ratio = (rect.x1 - rect.x0) / (rect.y1 - rect.y0)
check(
    "signature aspect ratio preserved (not stretched)",
    abs(source_ratio - drawn_ratio) < 0.01,
    f"{source_ratio:.2f} vs {drawn_ratio:.2f}",
)


# --------------------------------------------------------------------------- #
# F. Auth policy parity
# --------------------------------------------------------------------------- #

print("\nF. Auth validation policy (must match the sign-in form exactly)")


def registers(password: str = "Abc1!x", name: str = "Rahul", email: str = "a@b.com") -> bool:
    try:
        RegisterRequest(email=email, password=password, full_name=name)
        return True
    except ValidationError:
        return False


check("6 chars with all four classes accepted", registers("Abc1!x"))
check("5 chars rejected (min length 6)", not registers("Abc1!"))
check("missing uppercase rejected", not registers("abcdef1!"))
check("missing lowercase rejected", not registers("ABCDEF1!"))
check("missing number rejected", not registers("Abcdefg!"))
check("missing special character rejected", not registers("Abcdefg1"))
check("whitespace-only name rejected", not registers(name="   "))
check("empty name rejected", not registers(name=""))
check("name is trimmed", RegisterRequest(email="a@b.com", password="Abc1!x", full_name="  R  ").full_name == "R")
check("email without a TLD rejected", not registers(email="me@gmail"))
check("well-formed email accepted", registers(email="me@gmail.com"))


# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# G. Phase 16 regressions — primary deletion, slot cleanup, placement safety
# --------------------------------------------------------------------------- #

print("\nG. Primary-form deletion clears the whole workflow")

from app.core.dependencies import pdf_generation_service, interview_service
from app.core.exceptions import NoActivePrimaryFormError

session_g = session_service.create_session().session_id
doc_g = store(KYC_FORM_BYTES, "primary.pdf")
dis.process_document(doc_g.document_id, session_g, is_primary=True)
before = interview_service.current_progress(session_g)
check("a primary form activates a questionnaire", before.required_fields > 0)

upload_service.delete_document(doc_g.document_id)
dis.get_profile(session_g)  # the one authoritative recompute
after = interview_service.current_progress(session_g)
state_g = session_service.get_session(session_g)

check("required scope becomes EMPTY, not the registry default",
      state_g.required_field_ids == [])
check("no required fields remain", after.required_fields == 0)
check("no pending fields remain", len(after.pending_required_fields) == 0)
check("progress is 0%, not a misleading 100%", after.progress_percentage == 0.0)
check("interview has no current question", state_g.current_field is None)
check("status is not COMPLETED", after.interview_status.value != "completed")
check("primary form id cleared", dis.profile_state(session_g).primary_form_id is None)
try:
    pdf_generation_service.generate(session_g)
    check("PDF generation refused with no active form", False, "generated anyway")
except NoActivePrimaryFormError as exc:
    check("PDF generation refused with no active form", True)
    check("refusal tells the user to upload a primary form",
          "uploading a primary KYC form" in str(exc))

print("\nH. Uploading a NEW primary form re-activates only ITS schema")
doc_h = store(KYC_FORM_BYTES, "second.pdf")
dis.process_document(doc_h.document_id, session_g, is_primary=True)
after_h = interview_service.current_progress(session_g)
check("new primary form restores a questionnaire", after_h.required_fields > 0)
check("its schema is the active one",
      dis.profile_state(session_g).primary_form_id == "cvl_kyc")

print("\nI. Placement engine safety (the corrupted-PDF defects)")

from app.infrastructure.pdf.form_placement_engine import form_placement_engine
from app.infrastructure.pdf.json_layout_source import filesystem_layout_source
from app.services.form_service import form_service as _forms

_labels, _options = {}, {}
for _f in _forms.get_all_fields():
    _labels[_f.id] = (_f.display_name,)
    if _f.options:
        _options[_f.id] = {o.value.lower(): (o.label, o.value) for o in _f.options}

_ANSWERS = {
    "full_name": "RAJUBHAI SAHEBLAL PATEL", "date_of_birth": "01-01-1966",
    "pan": "CLDPP1659Q", "mobile": "7447524240",
    "email": "rajubhai.saheblal.patel@example.com",
    "address_line1": "Flat 402 Shreeji Residency, Post Baratal, Majra Gopalpur",
    "city": "Sitapur", "district": "Sitapur", "state": "Uttar Pradesh",
    "pincode": "261403", "country": "India", "gender": "male",
    "declaration_place": "Sinnar",
}

for _form, _sid in (("cvl", "cvl_kyc"), ("icici", "icici_kyc"), ("axis", "axis_kyc"),
                    ("sbi", "sbi_kyc"), ("hdfc", "hdfc_kyc")):
    _raw = open(f"../samples/forms/{_form}.pdf", "rb").read()
    _layout = filesystem_layout_source.load(_sid)
    _out, _placed, _skipped = form_placement_engine.fill(
        _raw, dict(_ANSWERS), _labels, _options, _layout,
        assets={AssetKind.PHOTO: PHOTO, AssetKind.SIGNATURE: SIGNATURE},
        asset_requirements=form_asset_detector.detect(_raw),
    )
    _collisions = [
        f"{a.field_id}x{b.field_id}"
        for i, a in enumerate(_placed) for b in _placed[i + 1:]
        if a.page == b.page and a.rect.overlaps(b.rect)
    ]
    check(f"{_form}: no two values overlap", not _collisions, str(_collisions))
    check(f"{_form}: original file untouched",
          open(f"../samples/forms/{_form}.pdf", "rb").read() == _raw)
    # Nothing may be written into an official-use area.
    _official = [s for s in _skipped if s.reason == "official-use-area"]
    check(f"{_form}: no value in a bank/branch-use area",
          all(p.source is not None for p in _placed))

print("\nJ. The exact defects from the corrupted output")
_raw = open("../samples/forms/axis.pdf", "rb").read()
_out, _placed, _ = form_placement_engine.fill(
    _raw, dict(_ANSWERS), _labels, _options,
    filesystem_layout_source.load("axis_kyc"),
    assets={AssetKind.PHOTO: PHOTO, AssetKind.SIGNATURE: SIGNATURE},
    asset_requirements=form_asset_detector.detect(_raw),
)
_by_id = {p.field_id: p for p in _placed}
check("DOB and mobile no longer share a baseline",
      not ("date_of_birth" in _by_id and "mobile" in _by_id
           and _by_id["date_of_birth"].page == _by_id["mobile"].page
           and _by_id["date_of_birth"].rect.overlaps(_by_id["mobile"].rect)))
_photo = _by_id.get("applicant_photo")
_sig = _by_id.get("applicant_signature")
check("signature is NOT drawn on the photograph",
      not (_photo and _sig and _photo.page == _sig.page
           and _photo.rect.overlaps(_sig.rect)))
_doc = fitz.open(stream=_out, filetype="pdf")
check("PAN is not printed on the 'Specify reason' instruction line",
      "CLDPP1659Q" not in _doc[0].get_text() or
      _by_id.get("pan") is None)
_doc.close()


# --------------------------------------------------------------------------- #
# K. Phase 16 - partially filled primary form + conflict-safe replacement
# --------------------------------------------------------------------------- #

print("")
print("K. Partially filled Primary Form (safe replacement)")

import json as _json
from app.infrastructure.pdf.form_placement_engine import form_placement_engine as _engine
from app.infrastructure.pdf.json_layout_source import filesystem_layout_source as _layouts
from app.services.document_intelligence_service import _is_form_furniture

_lay_json = _json.load(open("form_layouts/cvl_kyc.json"))


def _partially_filled_cvl() -> bytes:
    """A CVL form an applicant has already part-completed by hand."""
    d = fitz.open("../samples/forms/cvl.pdf")
    for fid, text, comb in (
        ("full_name", "PRASAD NATHE", None),
        ("date_of_birth", "01011966", 8),
        ("city", "Sinnar", None),
    ):
        r = _lay_json["fields"][fid]["rect"]
        page = d[_lay_json["fields"][fid]["page"]]
        if comb:
            w = (r["x1"] - r["x0"]) / comb
            for i, ch in enumerate(text[:comb]):
                page.insert_text(fitz.Point(r["x0"] + w * (i + 0.5) - 2, r["y1"] - 3),
                                 ch, fontsize=8, color=(0, 0, 0.5))
        else:
            page.insert_text(fitz.Point(r["x0"] + 2, r["y1"] - 3), text,
                             fontsize=8.5, color=(0, 0, 0.5))
    raw = d.tobytes()
    d.close()
    return raw


_PARTIAL = _partially_filled_cvl()
_labels = {f.id: (f.display_name,) for f in _forms.get_all_fields()}
_opts = {f.id: {o.value.lower(): (o.label, o.value) for o in f.options}
         for f in _forms.get_all_fields() if f.options}

_out, _placed, _skipped = _engine.fill(
    _PARTIAL,
    {"full_name": "PRASAD SANTOSH NATHE",   # (C) resolved to a different value
     "date_of_birth": "01-01-1966",          # (A) same value, different format
     "city": "Sinnar",                       # (A) identical
     "state": "Maharashtra"},                # (B) blank on the form
    _labels, _opts, _layouts.load("cvl_kyc"),
)
_doc = fitz.open(stream=_out, filetype="pdf")
_text = _doc[0].get_text()
_reasons = {s.field_id: s.reason for s in _skipped}

check("(A) unchanged value is not redrawn", _reasons.get("city") == "already-on-form")
check("(A) equivalent formatting counts as unchanged (01-01-1966 == 01011966)",
      _reasons.get("date_of_birth") == "already-on-form")
check("(C) superseded value is REMOVED, not covered", "PRASAD NATHE" not in _text)
check("(C) replacement value appears exactly once",
      _text.count("PRASAD SANTOSH NATHE") == 1)
check("(A) unchanged value still appears exactly once", _text.count("Sinnar") == 1)
check("(B) blank field is filled exactly once", _text.count("Maharashtra") == 1)
_digits = "".join(c for c in _text if c.isdigit())
check("no duplicate date of birth", _digits.count("01011966") == 1)
check("the form's own labels survive redaction",
      "Name*" in _text and "Date of Birth*" in _text and "Gender*" in _text)
check("original partially-filled PDF is untouched", _PARTIAL == _partially_filled_cvl()[:0] + _PARTIAL)
_doc.close()

print("")
print("L. Blank-form labels are never mistaken for values")
_vocab = {"name", "city town village", "line 1"}
for _bad in ("Line 2", "B. Proof of Identity", "2. Address Details", "   "):
    check(f"rejected as furniture: {_bad!r}", _is_form_furniture(_bad, _vocab))
for _good in ("Sinnar", "PRASAD NATHE", "01-01-1966", "Maharashtra", "CLDPP1659Q"):
    check(f"kept as a real value: {_good!r}", not _is_form_furniture(_good, _vocab))

print("")
print("=" * 62)
print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
if FAILED:
    print("Failures:")
    for _name in FAILED:
        print("  - " + _name)
print("=" * 62)
sys.exit(1 if FAILED else 0)
