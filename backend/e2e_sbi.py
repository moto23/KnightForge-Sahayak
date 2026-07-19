"""
SBI Annexure 'A' — targeted fixes.

Covers only the six SBI changes: District, State (always asked), Country,
Sources of Funds (multi-select), Email (always asked) and the declaration
Date/Place alignment.

Usage:  python e2e_sbi.py
"""

import asyncio
import io
import re
import sys
from pathlib import Path

import fitz
from fastapi import UploadFile

from app.core.dependencies import (
    asset_service,
    conversation_service,
    document_intelligence_service as dis,
    interview_service,
    session_service,
    upload_service,
)
from app.domain.enums import FieldType
from app.domain.form_assets import AssetKind
from app.domain.validators.engine import validation_engine
from app.infrastructure.pdf.form_placement_engine import form_placement_engine
from app.infrastructure.pdf.json_layout_source import filesystem_layout_source

from app.services.form_asset_detector import form_asset_detector
from app.services.form_service import form_service

SOURCE = Path("../samples/forms/sbi.pdf")
FILLED = Path(r"C:\Users\prasa\Downloads\kyc-filled-SBI.pdf")
OFFICE_USE_TOP = 611.0  # "For Office Use only" heading
RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
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


def main() -> int:
    original = SOURCE.read_bytes()
    layout = filesystem_layout_source.load("sbi_kyc")
    labels, options = vocabulary()
    assert layout is not None

    print("\n--- 1/3. District and Country are real fields now ---")
    ids = {f.id for f in form_service.get_all_fields()}
    check("district" in ids, "district is an interview field")
    check("country" in ids, "country is an interview field")
    check("district" in layout.fields, "district has a placement on the SBI form")
    check("country" in layout.fields, "country has a placement on the SBI form")

    print("\n--- 4. Sources of Funds is a multi-select ---")
    sof = field("sources_of_funds")
    check(sof.field_type == FieldType.MULTI_CHOICE, "declared MULTI_CHOICE")
    check([o.value for o in sof.options] == [
        "salary", "business_income", "agriculture",
        "investment_income", "pension", "others",
    ], "the six printed options, in the printed order")

    # Typed replies must select ONLY what was named.
    for reply, expected in (
        ("Salary and pension", "salary, pension"),
        ("salary", "salary"),
        ("Business Income, Agriculture", "business_income, agriculture"),
        ("investment income", "investment_income"),
    ):
        got = conversation_service._fallback_extract(sof, reply).value
        check(got == expected, f"{reply!r} -> {expected!r}", str(got))
    check(
        validation_engine.validate_field(sof, "salary, pension").valid,
        "a multi-value answer validates",
    )
    check(
        not validation_engine.validate_field(sof, "salary, lottery").valid,
        "an unknown option is rejected",
    )

    print("\n--- 6. Place accepts a place, never a yes/no ---")
    place = field("declaration_place")
    for bad in ("Yes", "No", "N/A", "true"):
        check(not validation_engine.validate_field(place, bad).valid,
              f"{bad!r} is rejected as a Place")
    for good in ("Sinnar", "New Delhi", "Nashik"):
        check(validation_engine.validate_field(place, good).valid,
              f"{good!r} is accepted as a Place")

    print("\n--- 2/5. State and Email are never taken from the document ---")
    check(FILLED.exists(), "the filled SBI fixture is available")
    sid = session_service.create_session().session_id
    doc = store(FILLED.read_bytes(), "sbi-filled.pdf")
    report = dis.process_document(doc.document_id, sid, is_primary=True)
    extracted = {v.canonical_id: v.value for v in report.state.documents[doc.document_id].values}
    answers = session_service.get_session(sid).answers

    # The bad reads that motivated this: they may still be EXTRACTED as
    # evidence, but must never become answers.
    check("state" not in answers, f"State is not auto-filled ({answers.get('state')!r})",
          str(answers.get("state")))
    check("email" not in answers, f"Email is not auto-filled ({answers.get('email')!r})",
          str(answers.get("email")))
    check(extracted.get("name") and "full_name" in answers,
          "other fields still prefill normally (name)")
    check("pan" in answers, "other fields still prefill normally (PAN)")

    print("\n--- the interview asks for exactly what is missing ---")
    required = set(session_service.get_session(sid).required_field_ids or ())
    for wanted in ("district", "country", "sources_of_funds", "state", "email"):
        check(wanted in required, f"{wanted} is required for SBI")

    # Supply the photo/signature up front so the asset questions are already
    # satisfied and the interview walks on to the remaining text fields.
    asset_service.store(sid, AssetKind.PHOTO, "photo.png", "image/png",
                        image(150, 190, (0.85, 0.2, 0.2)))
    asset_service.store(sid, AssetKind.SIGNATURE, "sign.png", "image/png",
                        image(240, 60, (0.1, 0.45, 0.15)))

    asked, guard = [], 0
    while guard < 40:
        guard += 1
        _, question = interview_service.next_question(sid)
        if question is None:
            break
        asked.append(question.id)
        value = {
            "state": "Uttar Pradesh", "email": "raju@example.com",
            "district": "Nashik", "country": "India",
            "sources_of_funds": "salary, pension",
            "declaration_place": "Sinnar", "declaration_date": "18-07-2026",
            "account_number": "30123456789", "ckycr_number": "12345678901234",
            "monthly_income": "45000",
        }.get(question.id)
        if value is None:
            if question.field_type == FieldType.ASSET:
                break
            value = question.options[0].value if question.options else "Sinnar"
        interview_service.submit_answer(sid, question.id, value)
    for wanted in ("state", "email", "district", "country", "sources_of_funds"):
        check(wanted in asked, f"the interview asked for {wanted}", str(asked))

    print("\n--- final PDF ---")
    answers = dict(session_service.get_session(sid).answers)
    out, placed, skipped = form_placement_engine.fill(
        original, answers, labels, options, layout,
        assets={AssetKind.PHOTO: image(150, 190, (0.85, 0.2, 0.2)),
                AssetKind.SIGNATURE: image(240, 60, (0.1, 0.45, 0.15))},
        asset_requirements=form_asset_detector.detect(original),
    )
    ids_placed = [p.field_id for p in placed]
    check(SOURCE.read_bytes() == original, "original PDF untouched")
    check(len(ids_placed) == len(set(ids_placed)), "each field placed exactly once")
    for wanted in ("district", "country", "state", "email",
                   "sources_of_funds", "declaration_place", "declaration_date"):
        check(wanted in ids_placed, f"placed: {wanted}")

    collisions = [
        f"{a.field_id}x{b.field_id}"
        for i, a in enumerate(placed) for b in placed[i + 1:]
        if a.page == b.page and a.rect.overlaps(b.rect)
    ]
    check(not collisions, f"no overlapping placements ({collisions})")
    check(all(p.rect.y0 < OFFICE_USE_TOP for p in placed),
          "nothing is written into the office-use block")

    doc_out = fitz.open(stream=out, filetype="pdf")
    page = doc_out[0]
    # Date on the Date line, Place on the Place line — and nothing else.
    date_line = page.get_text(clip=fitz.Rect(130, 585, 390, 599)).strip()
    place_line = page.get_text(clip=fitz.Rect(130, 599, 390, 611)).strip()
    check("18-07-2026" in date_line, f"Date line holds the date ({date_line!r})", date_line)
    check("Sinnar" in place_line, f"Place line holds the place ({place_line!r})", place_line)
    check("Yes" not in place_line and "18-07-2026" not in place_line,
          f"Place line holds nothing else ({place_line!r})", place_line)
    check("Sinnar" not in date_line, f"Date line holds nothing else ({date_line!r})", date_line)

    district_cell = page.get_text(clip=fitz.Rect(390, 311, 568, 325))
    check("Nashik" in district_cell, f"District prints in its cell ({district_cell.strip()!r})")

    # Exactly the two chosen ticks, in the right columns, and no others.
    ticks = [w for w in page.get_text("words")
             if 415 <= w[1] <= 432 and w[0] > 170]
    check(len(ticks) == 2, f"exactly two ticks in the Sources row ({len(ticks)})",
          str([(round(t[0]), t[4]) for t in ticks]))
    xs = sorted(round(t[0]) for t in ticks)
    check(180 <= xs[0] <= 200, f"a tick under Salary (x={xs[0] if xs else '-'})")
    check(475 <= xs[1] <= 495, f"a tick under Pension (x={xs[1] if len(xs) > 1 else '-'})")
    doc_out.close()

    print("\n--- blank form still yields nothing ---")
    sid2 = session_service.create_session().session_id
    doc2 = store(original, "sbi.pdf")
    rep2 = dis.process_document(doc2.document_id, sid2, is_primary=True)
    check(not rep2.state.documents[doc2.document_id].values, "blank form extracts nothing")
    check(not session_service.get_session(sid2).answers, "blank form prefills nothing")
    blank_out = form_placement_engine.fill(
        original, {}, labels, options, layout, assets={},
        asset_requirements=form_asset_detector.detect(original),
    )
    check(not blank_out[1], "blank answers place nothing")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{'=' * 60}")
    print(f"SBI: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for label in failed:
        print(f"  FAILED: {label}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
