"""
ICICI Central-KYC form — focused regression suite.

The new ICICI template is a 3-page CKYC form with NO AcroForm widgets and no
bank branding, replacing a 133-widget Re-KYC form. Everything here is checked
against the real PDF in samples/forms/icici.pdf.

Usage:  python e2e_icici.py
"""

import re
import sys
from pathlib import Path

import fitz

from app.domain.form_assets import AssetKind
from app.domain.form_layout import FormLayout
from app.infrastructure.intelligence import FileSystemSchemaSource
from app.infrastructure.pdf.form_placement_engine import form_placement_engine
from app.infrastructure.pdf.json_layout_source import filesystem_layout_source
from app.services.document_classifier import document_classifier
from app.services.form_asset_detector import form_asset_detector
from app.services.form_service import form_service

SOURCE = Path("../samples/forms/icici.pdf")
RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> bool:
    RESULTS.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return bool(ok)


def vocabulary():
    labels, options = {}, {}
    for field in form_service.get_all_fields():
        labels[field.id] = (field.display_name,)
        if field.options:
            options[field.id] = {
                o.value.lower(): (o.label, o.value) for o in field.options
            }
    return labels, options


ANSWERS = {
    "full_name": "RAJUBHAI SAHEBLAL PATEL",
    "father_spouse_name": "SAHEBLAL BABASO PATEL",
    "mother_name": "SUNITA PATEL",
    "date_of_birth": "01-01-1966",
    "gender": "male",
    "marital_status": "married",
    "nationality": "indian",
    "residential_status": "resident_individual",
    "occupation": "private_sector",
    "poi_document": "uid_aadhaar",
    "poa_document": "driving_licence",
    "pan": "CLDPP1659Q",
    "aadhaar": "844587274125",
    "ckycr_number": "12345678901234",
    "correspondence_address": "Flat 402 Shreeji Residency, Post Baratal",
    "city": "Sitapur",
    "pincode": "261403",
    "mobile": "7447524240",
    "email": "raju@example.com",
    "telephone_office": "27123456",
    "telephone_residence": "27987654",
    "other_information": "No other information to declare",
    "declaration_place": "Sinnar",
    "declaration_date": "18-07-2026",
}


def image(width: int, height: int, rgb) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(0, 0, width, height), color=rgb, fill=rgb)
    raw = page.get_pixmap().tobytes("png")
    doc.close()
    return raw


def text_of(raw: bytes, page_no: int) -> str:
    doc = fitz.open(stream=raw, filetype="pdf")
    out = doc[page_no].get_text()
    doc.close()
    return out


def squashed(raw: bytes, page_no: int) -> str:
    """Page text with all whitespace removed — comb cells are space-separated."""
    return re.sub(r"\s+", "", text_of(raw, page_no))


def main() -> int:
    original = SOURCE.read_bytes()
    layout = filesystem_layout_source.load("icici_kyc")
    labels, options = vocabulary()

    print("\n--- manifest + classification ---")
    check(isinstance(layout, FormLayout), "manifest loads")
    assert layout is not None
    check(layout.has_text_layer, "declared as a text-layer PDF (not a scan)")

    schemas = FileSystemSchemaSource().load_all()
    doc = fitz.open(stream=original, filetype="pdf")
    full_text = " ".join(p.get_text() for p in doc)
    check(doc.page_count == 3, "template is 3 pages")
    check(sum(len(list(p.widgets())) for p in doc) == 0, "no AcroForm widgets remain")
    doc.close()
    verdict = document_classifier.classify(full_text, schemas)
    check(verdict.schema_id == "icici_kyc", "classifies as icici_kyc")

    # The CKYC form is a shared format: CVL must not be captured by it.
    cvl_text = " ".join(
        p.get_text() for p in fitz.open("../samples/forms/cvl.pdf")
    )
    check(
        document_classifier.classify(cvl_text, schemas).schema_id == "cvl_kyc",
        "CVL still classifies as cvl_kyc (not captured by the CKYC markers)",
    )

    print("\n--- asset requirements ---")
    requirements = form_asset_detector.detect(original)
    check(requirements is not None, "photo/signature requirement detected")

    print("\n--- blank form: no false prefills ---")
    blank = form_placement_engine.fill(
        original, {}, labels, options, layout,
        assets={}, asset_requirements=requirements,
    )
    check(len(blank[1]) == 0, "blank form places nothing")

    print("\n--- filled render ---")
    out, placed, skipped = form_placement_engine.fill(
        original, dict(ANSWERS), labels, options, layout,
        assets={
            AssetKind.PHOTO: image(150, 190, (0.85, 0.2, 0.2)),
            AssetKind.SIGNATURE: image(240, 60, (0.1, 0.45, 0.15)),
        },
        asset_requirements=requirements,
    )
    ids = [p.field_id for p in placed]
    check(SOURCE.read_bytes() == original, "original PDF untouched on disk")
    check(len(ids) == len(set(ids)), "each field reported exactly once")

    for field_id in (
        "full_name", "father_spouse_name", "mother_name", "date_of_birth",
        "gender", "marital_status", "nationality", "residential_status",
        "occupation", "poi_document", "poa_document", "pan", "aadhaar",
        "ckycr_number", "correspondence_address", "city", "pincode",
        "mobile", "email", "telephone_office", "telephone_residence",
        "other_information", "declaration_place", "declaration_date",
    ):
        check(field_id in ids, f"placed: {field_id}")
    check("applicant_photo" in ids, "placed: photograph")
    check("applicant_signature" in ids, "placed: signature")

    unexpected = [s for s in skipped if s.reason not in ("not-on-form", "no-target")]
    check(not unexpected, f"no unexpected skips ({[s.field_id for s in unexpected]})")

    print("\n--- geometry: nothing collides ---")
    collisions = [
        f"{a.field_id}x{b.field_id}"
        for i, a in enumerate(placed)
        for b in placed[i + 1:]
        if a.page == b.page and a.rect.overlaps(b.rect)
    ]
    check(not collisions, f"no overlapping placements ({collisions})")

    print("\n--- values land correctly ---")
    p1, p2 = squashed(out, 0), squashed(out, 1)
    check("RAJUBHAI" in p1 and "SAHEBLAL" in p1 and "PATEL" in p1,
          "name split across First/Middle/Last")
    check(p1.count("CLDPP1659Q") == 1, "PAN written exactly once")
    check("844587274125" in p1, "Aadhaar written")
    check("12345678901234" in p1, "KYC number written")
    # DD MM YYYY across three cell groups, not DDMMYYYY jammed into one.
    check("01011966" in p1, "date of birth reads 01011966")
    check("18072026" in p2, "declaration date reads 18072026")
    check("7447524240" in p2, "mobile written")
    check("raju@example.com" in p2, "email written in full (fits 29 cells)")

    print("\n--- office-use and instructions are untouched ---")
    check(text_of(out, 2) == text_of(original, 2), "page 3 instructions byte-identical")
    check(
        all(not (p.page == 1 and p.rect.y0 >= 625) for p in placed),
        "nothing placed in section 9 (attestation / office use)",
    )
    check(
        all(p.page != 2 for p in placed),
        "nothing placed on the instructions page",
    )

    print("\n--- partially filled form: replace, never overprint ---")
    partial = form_placement_engine.fill(
        out, dict(ANSWERS), labels, options, layout,
        assets={}, asset_requirements=requirements,
    )
    again = squashed(partial[0], 0)
    check(again.count("CLDPP1659Q") == 1, "re-filling does not duplicate the PAN")
    check(
        sum(1 for s in partial[2] if s.reason == "already-on-form") > 0,
        "unchanged values are recognised as already on the form",
    )

    changed = dict(ANSWERS, pan="ABCDE1234F")
    replaced = form_placement_engine.fill(
        out, changed, labels, options, layout,
        assets={}, asset_requirements=requirements,
    )
    swapped = squashed(replaced[0], 0)
    check("ABCDE1234F" in swapped, "changed PAN is written")
    check("CLDPP1659Q" not in swapped, "superseded PAN is removed, not covered")

    print("\n--- capacity: a value is written in FULL or not at all ---")
    # The email box is 29 cells. A longer address used to be sliced to 29
    # characters, which reads as a real address and is not one.
    long_email = "rajubhai.saheblal.patel@example.com"  # 35 chars
    check(len(long_email) > 29, "the test address genuinely exceeds the cells")
    over = form_placement_engine.fill(
        original, dict(ANSWERS, email=long_email), labels, options, layout,
        assets={}, asset_requirements=requirements,
    )
    page2 = squashed(over[0], 1)
    check(long_email in page2, "an oversized email is written COMPLETE, not truncated")
    check("patel@examp" not in page2.replace(long_email, ""),
          "no truncated remnant of the email is left on the page")
    check("email" in [p.field_id for p in over[1]], "the oversized email still counts as placed")

    # Short enough to keep one-character-per-cell layout: the comb path must
    # not have been disturbed for the values that always fitted.
    fitted_ids = [p.field_id for p in over[1]]
    check("pan" in fitted_ids and "pincode" in fitted_ids,
          "values that fit still take the comb path")

    # A value too long even for the smallest legible type must leave the box
    # ALONE rather than print a partial answer.
    absurd = ("averyveryverylongmailboxname" * 6) + "@example.com"
    huge = form_placement_engine.fill(
        original, dict(ANSWERS, email=absurd), labels, options, layout,
        assets={}, asset_requirements=requirements,
    )
    reasons = {s.field_id: s.reason for s in huge[2]}
    check(reasons.get("email") == "value-too-long",
          f"an unplaceable value is skipped and reported ({reasons.get('email')})")
    check("email" not in [p.field_id for p in huge[1]],
          "an unplaceable value is not reported as placed")
    check("averyvery" not in squashed(huge[0], 1),
          "no fragment of an unplaceable value is drawn")

    # Refusing must happen BEFORE redaction: an existing correct value on a
    # partially-filled form must survive an unplaceable replacement.
    keep = form_placement_engine.fill(
        out, dict(ANSWERS, email=absurd), labels, options, layout,
        assets={}, asset_requirements=requirements,
    )
    check("raju@example.com" in squashed(keep[0], 1),
          "an unplaceable replacement does not erase the value already on the form")

    # Name columns are 12 cells; a longer part must not lose its tail.
    long_name = "SATYANARAYANAN VENKATASUBRAMANIAN IYER"
    named = form_placement_engine.fill(
        original, dict(ANSWERS, full_name=long_name), labels, options, layout,
        assets={}, asset_requirements=requirements,
    )
    page1 = squashed(named[0], 0)
    for part in long_name.split():
        check(part in page1, f"long name part written in full: {part}")

    print("\n--- the interview asks for the fields this form needs ---")
    import asyncio as _asyncio, io as _io
    from fastapi import UploadFile as _UploadFile
    from app.core.dependencies import (
        document_intelligence_service as _dis, interview_service as _interview,
        session_service as _sessions, upload_service as _uploads,
    )
    sid = _sessions.create_session().session_id
    stored = _asyncio.run(_uploads.store_upload(_UploadFile(
        file=_io.BytesIO(original), filename="icici.pdf",
        headers={"content-type": "application/pdf"})))
    _dis.process_document(stored.document_id, sid, is_primary=True)
    required = set(_sessions.get_session(sid).required_field_ids or ())
    for wanted in (
        "ckycr_number", "application_type", "mother_name", "marital_status",
        "nationality", "residential_status", "occupation", "email",
        "address_type", "poa_document", "correspondence_same_as_permanent",
        "declaration_place", "declaration_date",
    ):
        check(wanted in required, f"the interview requires {wanted}")

    # Email must be asked, never inherited from a document read.
    schema = next(s for s in schemas if s.id == "icici_kyc")
    check("email" in schema.never_prefill, "email is declared never-prefill")

    print("\n--- Place refuses a yes/no answer ---")
    from app.domain.validators.engine import validation_engine as _ve
    place_field = next(f for f in form_service.get_all_fields()
                       if f.id == "declaration_place")
    for bad in ("Yes", "No", "true"):
        check(not _ve.validate_field(place_field, bad).valid,
              f"{bad!r} is rejected as a Place")
    check(_ve.validate_field(place_field, "Sinnar").valid, "'Sinnar' is accepted")

    print("\n--- new choice fields tick ONLY what was chosen ---")
    picked = dict(
        ANSWERS, application_type="new", address_type="residential",
        poa_document="driving_licence", correspondence_same_as_permanent="yes",
        declaration_place="Sinnar", declaration_date="18-07-2026",
    )
    chosen = form_placement_engine.fill(
        original, picked, labels, options, layout, assets={},
        asset_requirements=requirements,
    )
    by_id = {p.field_id: p for p in chosen[1]}
    for field_id, x0 in (("application_type", 192.6), ("address_type", 224.6),
                         ("poa_document", 224.6)):
        check(field_id in by_id and abs(by_id[field_id].rect.x0 - x0) < 0.5,
              f"{field_id} ticks the chosen box (x={by_id[field_id].rect.x0 if field_id in by_id else '-'})")
    same_as = by_id.get("correspondence_same_as_permanent")
    check(same_as is not None and same_as.page == 1 and abs(same_as.rect.y0 - 47.6) < 0.5,
          "the 4.2 'same as' box is ticked (section 4.2, not 4.3)")

    # One tick per choice field — never a second option, never all of them.
    marked = fitz.open(stream=chosen[0], filetype="pdf")
    boxes = [by_id[f].rect for f in ("application_type", "address_type", "poa_document")]
    inside = [
        w for w in marked[0].get_text("words")
        if any(b.x0 - 1 <= w[0] <= b.x1 + 1 and b.y0 - 1 <= w[1] <= b.y1 + 1 for b in boxes)
    ]
    marked.close()
    check(len(inside) == 3, f"exactly one mark in each chosen box ({len(inside)})")

    # Answering "no" must tick nothing at all.
    declined = form_placement_engine.fill(
        original, dict(picked, correspondence_same_as_permanent="no"),
        labels, options, layout, assets={}, asset_requirements=requirements,
    )
    check("correspondence_same_as_permanent" not in [p.field_id for p in declined[1]],
          "answering No ticks no box")

    print("\n--- declaration: Date to Date, Place to Place ---")
    filled_doc = fitz.open(stream=chosen[0], filetype="pdf")
    page2 = filled_doc[1]
    date_cells = re.sub(r"\s+", "", page2.get_text(clip=fitz.Rect(45, 602, 160, 618)))
    place_cells = re.sub(r"\s+", "", page2.get_text(clip=fitz.Rect(223, 601, 360, 617)))
    filled_doc.close()
    check("18072026" in date_cells, f"Date cells hold the date ({date_cells!r})")
    check("Sinnar" in place_cells, f"Place cells hold the place ({place_cells!r})")
    check("Sinnar" not in date_cells, "the Date boxes hold nothing else")
    check("18072026" not in place_cells, "the Place boxes hold nothing else")

    print("\n--- a blank form still ticks nothing ---")
    # A printed "3" appears in section numbers, so look INSIDE the option
    # boxes instead: on a blank form every one of them must be empty.
    untouched = fitz.open(stream=original, filetype="pdf")
    every_box = [
        (placement.page, box)
        for placement in layout.fields.values()
        for boxes in placement.option_rects.values()
        for box in boxes
    ]
    occupied = [
        (page_no, w[4]) for page_no, box in every_box
        for w in untouched[page_no].get_text("words")
        if box.x0 - 1 <= w[0] <= box.x1 + 1 and box.y0 - 1 <= w[1] <= box.y1 + 1
    ]
    untouched.close()
    check(not occupied, f"every option box is empty on the blank template ({occupied[:4]})")

    print("\n--- occupation ticks BOTH the category and its sub-category ---")
    doc = fitz.open(stream=out, filetype="pdf")
    marks = [
        w for w in doc[0].get_text("words")
        if w[4] == "X" and 370 <= w[1] <= 382
    ]
    doc.close()
    check(len(marks) == 2, f"S-Service and Private Sector both ticked ({len(marks)})")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{'=' * 60}")
    print(f"ICICI: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        for label in failed:
            print(f"  FAILED: {label}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
