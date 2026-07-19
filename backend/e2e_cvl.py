"""
CVL (CDSL) KYC — targeted fixes.

Covers only the requested CVL changes: the six tick-box groups, the
Correspondence Line 1 / District mapping, Proof of Address plus its
identification number, Email (always asked) and the declaration Date/Place.

Usage:  python e2e_cvl.py
"""

import asyncio
import io
import re
import sys
from pathlib import Path

import fitz
from fastapi import UploadFile

from app.core.dependencies import (
    document_intelligence_service as dis,
    session_service,
    upload_service,
)
from app.domain.form_assets import AssetKind
from app.domain.validators.engine import validation_engine
from app.infrastructure.pdf.form_placement_engine import form_placement_engine
from app.infrastructure.pdf.json_layout_source import filesystem_layout_source
from app.services.form_asset_detector import form_asset_detector
from app.services.form_service import form_service

SOURCE = Path("../samples/forms/cvl.pdf")
OFFICE_USE_TOP = 600.0  # "5. For Office Use Only" band on page 2
# CVL draws the Application Type boxes as Wingdings glyphs rather than
# vector rectangles, so the empty box itself is a "word" sitting inside the
# rect. It is printed furniture, not a mark.
PRINTED_BOX = ""
RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> bool:
    RESULTS.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return bool(ok)


def store(raw: bytes, name: str):
    return asyncio.run(upload_service.store_upload(UploadFile(
        file=io.BytesIO(raw), filename=name,
        headers={"content-type": "application/pdf"})))


def vocabulary():
    labels, options = {}, {}
    for field in form_service.get_all_fields():
        labels[field.id] = (field.display_name,)
        if field.options:
            options[field.id] = {o.value.lower(): (o.label, o.value) for o in field.options}
    return labels, options


def field(field_id: str):
    return next(f for f in form_service.get_all_fields() if f.id == field_id)


def image(w, h, rgb) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    page.draw_rect(fitz.Rect(0, 0, w, h), color=rgb, fill=rgb)
    raw = page.get_pixmap().tobytes("png")
    doc.close()
    return raw


ANSWERS = {
    "full_name": "RAJUBHAI SAHEBLAL PATEL",
    "father_spouse_name": "SAHEBLAL BABASO PATEL",
    "date_of_birth": "01-01-1966",
    "pan": "CLDPP1659Q",
    "application_type": "new",
    "kyc_mode": "normal",
    "gender": "male",
    "marital_status": "single",
    "nationality": "indian",
    "residential_status": "resident_individual",
    "correspondence_address": "Flat 402 Shreeji Residency, Post Baratal",
    "city": "Sitapur",
    "district": "Nashik",
    "state": "Uttar Pradesh",
    "pincode": "261403",
    "country": "India",
    "poa_document": "driving_licence",
    "poa_document_number": "MH0120110012345",
    "mobile": "7447524240",
    "email": "raju@example.com",
    "declaration_place": "Sinnar",
    "declaration_date": "15-07-2026",
}

# Every choice group, with the box that MUST be marked and the boxes that
# must stay empty.
CHOICE_GROUPS = ("application_type", "kyc_mode", "gender", "marital_status",
                 "nationality", "residential_status", "poa_document")


def main() -> int:
    original = SOURCE.read_bytes()
    layout = filesystem_layout_source.load("cvl_kyc")
    labels, options = vocabulary()
    assert layout is not None

    print("\n--- 1. every requested choice group is mapped to measured boxes ---")
    for group in CHOICE_GROUPS:
        placement = layout.fields.get(group)
        check(placement is not None and bool(placement.option_rects),
              f"{group} has measured option boxes")
        check(placement is not None and placement.tick_check_mark,
              f"{group} is marked with a check mark")
    # The whole point of measured boxes: caption anchoring put the nationality
    # tick beside the WRONG option.
    check(not any(layout.fields[g].option_anchors for g in CHOICE_GROUPS),
          "no choice group relies on caption anchoring any more")
    check(len(layout.fields["kyc_mode"].option_rects) == 6, "KYC Mode offers six modes")
    check(len(layout.fields["residential_status"].option_rects) == 4,
          "Residential Status offers all four options")
    check(len(layout.fields["poa_document"].option_rects) == 7,
          "Proof of Address offers all seven printed documents")

    print("\n--- the interview asks for them ---")
    sid = session_service.create_session().session_id
    doc = store(original, "cvl.pdf")
    dis.process_document(doc.document_id, sid, is_primary=True)
    required = set(session_service.get_session(sid).required_field_ids or ())
    for wanted in ("application_type", "kyc_mode", "gender", "marital_status",
                   "nationality", "residential_status", "district",
                   "poa_document", "poa_document_number", "email",
                   "declaration_place", "declaration_date"):
        check(wanted in required, f"the interview requires {wanted}")

    print("\n--- 4. Email is asked, never inherited from the document ---")
    from app.infrastructure.intelligence import FileSystemSchemaSource
    schema = next(s for s in FileSystemSchemaSource().load_all() if s.id == "cvl_kyc")
    check("email" in schema.never_prefill, "email is declared never-prefill for CVL")

    print("\n--- 5. Place refuses a yes/no answer ---")
    place = field("declaration_place")
    for bad in ("Yes", "No", "true"):
        check(not validation_engine.validate_field(place, bad).valid,
              f"{bad!r} is rejected as a Place")
    check(validation_engine.validate_field(place, "Sinnar").valid, "'Sinnar' is accepted")

    print("\n--- blank form places nothing ---")
    blank = form_placement_engine.fill(
        original, {}, labels, options, layout, assets={},
        asset_requirements=form_asset_detector.detect(original),
    )
    check(not blank[1], "blank answers place nothing")
    # No option box may already carry a mark on the untouched template.
    template = fitz.open(stream=original, filetype="pdf")
    prefilled = [
        (p.page, w[4])
        for group in CHOICE_GROUPS
        for boxes in layout.fields[group].option_rects.values()
        for box in boxes
        for p in [layout.fields[group]]
        for w in template[p.page].get_text("words")
        if box.x0 - 1 <= w[0] <= box.x1 + 1 and box.y0 - 1 <= w[1] <= box.y1 + 1
        and w[4] != PRINTED_BOX
    ]
    template.close()
    check(not prefilled, f"every option box is empty on the blank template ({prefilled[:3]})")

    print("\n--- final PDF ---")
    out, placed, skipped = form_placement_engine.fill(
        original, dict(ANSWERS), labels, options, layout,
        assets={AssetKind.PHOTO: image(150, 190, (0.85, 0.2, 0.2)),
                AssetKind.SIGNATURE: image(240, 60, (0.1, 0.45, 0.15))},
        asset_requirements=form_asset_detector.detect(original),
    )
    ids = [p.field_id for p in placed]
    check(SOURCE.read_bytes() == original, "original PDF untouched")
    check(len(ids) == len(set(ids)), "each field placed exactly once")
    for wanted in (*CHOICE_GROUPS, "correspondence_address", "district",
                   "poa_document_number", "email",
                   "declaration_place", "declaration_date"):
        check(wanted in ids, f"placed: {wanted}")

    collisions = [
        f"{a.field_id}x{b.field_id}"
        for i, a in enumerate(placed) for b in placed[i + 1:]
        if a.page == b.page and a.rect.overlaps(b.rect)
    ]
    check(not collisions, f"no overlapping placements ({collisions})")

    print("\n--- exactly ONE tick per group, on the chosen option ---")
    marked = fitz.open(stream=out, filetype="pdf")
    for group in CHOICE_GROUPS:
        placement = layout.fields[group]
        chosen = ANSWERS[group]
        hits = {
            value: [
                w for box in boxes
                for w in marked[placement.page].get_text("words")
                if box.x0 - 1 <= w[0] <= box.x1 + 1 and box.y0 - 1 <= w[1] <= box.y1 + 1
                and w[4] != PRINTED_BOX
            ]
            for value, boxes in placement.option_rects.items()
        }
        check(len(hits[chosen]) == 1, f"{group}: the chosen box {chosen!r} is ticked")
        others = {v: h for v, h in hits.items() if v != chosen and h}
        check(not others, f"{group}: no other option is ticked ({list(others)})")

    print("\n--- 2. address, 3. PoA number, 5. declaration ---")
    page1, page2 = marked[0], marked[1]
    line1 = page1.get_text(clip=fitz.Rect(75, 604, 560, 620)).strip()
    check("Shreeji" in line1, f"Line 1 holds the correspondence address ({line1!r})")
    district = page1.get_text(clip=fitz.Rect(310, 659, 422, 675)).strip()
    check("Nashik" in district, f"District holds the district ({district!r})")

    poa_number = page2.get_text(clip=fitz.Rect(168, 315, 318, 331)).strip()
    check("MH0120110012345" in poa_number,
          f"the PoA identification number is on its line ({poa_number!r})")

    date_line = re.sub(r"\s+", "", page2.get_text(clip=fitz.Rect(63, 539, 160, 554)))
    place_line = page2.get_text(clip=fitz.Rect(64, 553, 222, 567)).strip()
    check("15072026" in date_line, f"DATE holds only the date ({date_line!r})")
    check("Sinnar" in place_line, f"PLACE holds the place ({place_line!r})")
    check("Sinnar" not in date_line, "DATE holds nothing else")
    check("15072026" not in place_line and "Yes" not in place_line,
          f"PLACE holds nothing else ({place_line!r})")
    marked.close()

    print("\n--- office-use area is untouched ---")
    check(all(not (p.page == 1 and p.rect.y0 >= OFFICE_USE_TOP) for p in placed),
          "nothing is written into section 5 (For Office Use Only)")
    check(all(p.page < 2 for p in placed), "nothing is written on the guideline pages")
    for page_no in (2, 3):
        before = fitz.open(stream=original, filetype="pdf")
        after = fitz.open(stream=out, filetype="pdf")
        same = before[page_no].get_text() == after[page_no].get_text()
        before.close(); after.close()
        check(same, f"page {page_no + 1} (guidelines) is unchanged")

    print("\n--- a partially filled form keeps its values ---")
    again = form_placement_engine.fill(
        out, dict(ANSWERS), labels, options, layout, assets={},
        asset_requirements=form_asset_detector.detect(original),
    )
    body = re.sub(r"\s+", "", fitz.open(stream=again[0], filetype="pdf")[0].get_text())
    check(body.count("CLDPP1659Q") == 1, "re-filling does not duplicate the PAN")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{'=' * 60}")
    print(f"CVL: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for label in failed:
        print(f"  FAILED: {label}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
