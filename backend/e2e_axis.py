"""
Axis CKYC form — focused regression suite.

The new Axis template (CK001) is a 2-page Central KYC Registry form that
repeats an IDENTICAL applicant block four times: Primary, 1st Joint and 2nd
Joint on page 1, 3rd Joint plus For-Office-Use on page 2. Sahayak supports one
applicant, so the whole point of this suite is that ONLY the Primary block is
ever written to and the three Joint blocks come out untouched.

Because the blocks are textually identical, caption matching cannot tell them
apart — every field here is pinned to a measured rectangle inside the Primary
block, and everything below it is an excluded region.

Usage:  python e2e_axis.py
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

SOURCE = Path("../samples/forms/axis.pdf")
# Everything at or below this y on page 1 belongs to a Joint Applicant.
PRIMARY_BOTTOM = 336.0
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
    "spouse_name": "ANJALI PATEL",
    "occupation": "private_sector",
    "declaration_place": "Sinnar",
    "declaration_date": "18-07-2026",
    # Deliberately supplied but absent from this form: none of these may appear.
    "pan": "CLDPP1659Q",
    "aadhaar": "844587274125",
    "date_of_birth": "01-01-1966",
    "mobile": "7447524240",
    "email": "raju@example.com",
    "correspondence_address": "Flat 402 Shreeji Residency",
    "city": "Sitapur",
    "state": "Uttar Pradesh",
    "pincode": "261403",
}


def image(width: int, height: int, rgb) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(0, 0, width, height), color=rgb, fill=rgb)
    raw = page.get_pixmap().tobytes("png")
    doc.close()
    return raw


def region_text(raw: bytes, page_no: int, clip: fitz.Rect | None = None) -> str:
    doc = fitz.open(stream=raw, filetype="pdf")
    out = doc[page_no].get_text(clip=clip)
    doc.close()
    return out


def squashed(raw: bytes, page_no: int, clip: fitz.Rect | None = None) -> str:
    return re.sub(r"\s+", "", region_text(raw, page_no, clip))


def main() -> int:
    original = SOURCE.read_bytes()
    layout = filesystem_layout_source.load("axis_kyc")
    labels, options = vocabulary()

    print("\n--- manifest + classification ---")
    check(isinstance(layout, FormLayout), "manifest loads")
    assert layout is not None
    check(layout.has_text_layer, "declared as a text-layer PDF")

    doc = fitz.open(stream=original, filetype="pdf")
    check(doc.page_count == 2, "template is 2 pages")
    check(sum(len(list(p.widgets())) for p in doc) == 0, "no AcroForm widgets")
    full_text = " ".join(p.get_text() for p in doc)
    doc.close()

    schemas = FileSystemSchemaSource().load_all()
    check(document_classifier.classify(full_text, schemas).schema_id == "axis_kyc",
          "classifies as axis_kyc")
    # Both this and the ICICI template are Central-KYC forms; the markers must
    # not let either swallow the other.
    for other, expected in (("icici", "icici_kyc"), ("cvl", "cvl_kyc")):
        text = " ".join(p.get_text() for p in fitz.open(f"../samples/forms/{other}.pdf"))
        check(document_classifier.classify(text, schemas).schema_id == expected,
              f"{other} still classifies as {expected}")

    print("\n--- classification rests on template evidence, not generic CKYC text ---")
    axis_schema = next(s for s in schemas if s.id == "axis_kyc")
    score, strong, _ = document_classifier._score(full_text, axis_schema)
    check(strong >= 2, f"the real template matches several STRONG markers ({strong})")
    check(score >= axis_schema.markers.min_score, "the real template clears min_score")
    # This form carries no textual "Axis" branding (the logo is an image), so
    # the danger is a DIFFERENT bank's Central-KYC form scoring on shared
    # wording alone. It must fall short on its own, not merely lose a tie.
    for other in ("icici", "cvl", "sbi", "hdfc"):
        text = " ".join(p.get_text() for p in fitz.open(f"../samples/forms/{other}.pdf"))
        other_score, other_strong, _ = document_classifier._score(text, axis_schema)
        check(
            other_score < axis_schema.markers.min_score and other_strong == 0,
            f"{other} cannot reach the Axis threshold on its own "
            f"(score {other_score}, strong {other_strong})",
        )

    print("\n--- assets: this form has NO photograph box ---")
    requirements = form_asset_detector.detect(original)
    check(requirements is not None, "asset requirements detected")
    assert requirements is not None
    check(not requirements.photo, "no photograph is required (the form has no photo box)")
    check(requirements.signature, "a signature IS required")

    print("\n--- the layout is PROVEN before anything is written ---")
    check(bool(layout.layout_guards), "the manifest declares structural guards")
    check(
        form_placement_engine._layout_verified(
            fitz.open(stream=original, filetype="pdf"), layout
        ),
        "the served template passes its own guards",
    )

    # A copy paginated differently would put Primary-block rectangles over a
    # JOINT applicant's row. Simulate one by shifting the page content down.
    shifted = fitz.open()
    src = fitz.open(stream=original, filetype="pdf")
    for page in src:
        new = shifted.new_page(width=page.rect.width, height=page.rect.height)
        new.show_pdf_page(
            fitz.Rect(0, 40, page.rect.width, page.rect.height + 40), src, page.number
        )
    moved = shifted.tobytes()
    src.close()
    shifted.close()
    guarded = form_placement_engine.fill(
        moved, dict(ANSWERS), labels, options, layout,
        assets={AssetKind.SIGNATURE: image(240, 60, (0.1, 0.45, 0.15))},
        asset_requirements=requirements,
    )
    check(not guarded[1], "a shifted layout places NOTHING")
    check(
        bool(guarded[2]) and all(s.reason == "layout-unverified" for s in guarded[2]),
        "every field is reported layout-unverified",
    )
    check(guarded[0] == moved, "a refused layout is returned completely unmodified")

    print("\n--- blank form: no false prefills ---")
    blank = form_placement_engine.fill(
        original, {}, labels, options, layout, assets={},
        asset_requirements=requirements,
    )
    check(len(blank[1]) == 0, "blank form places nothing")

    print("\n--- filled render ---")
    out, placed, skipped = form_placement_engine.fill(
        original, dict(ANSWERS), labels, options, layout,
        assets={AssetKind.SIGNATURE: image(240, 60, (0.1, 0.45, 0.15))},
        asset_requirements=requirements,
    )
    ids = [p.field_id for p in placed]
    check(SOURCE.read_bytes() == original, "original PDF untouched on disk")
    check(len(ids) == len(set(ids)), "each field reported exactly once")
    for field_id in (
        "full_name", "father_spouse_name", "mother_name", "spouse_name",
        "occupation", "declaration_place", "declaration_date",
    ):
        check(field_id in ids, f"placed: {field_id}")
    check("applicant_signature" in ids, "placed: signature")

    print("\n--- ONLY the Primary Applicant block is written to ---")
    check(
        all(p.page == 0 for p in placed),
        "nothing is placed on page 2 (3rd Joint + office use)",
    )
    below = [p.field_id for p in placed if p.rect.y1 > PRIMARY_BOTTOM]
    check(not below, f"nothing is placed below the Primary block ({below})")

    # The Joint blocks must be byte-for-byte the same text as the blank form.
    joint_clip = fitz.Rect(0, PRIMARY_BOTTOM, 598, 860)
    check(
        region_text(out, 0, joint_clip) == region_text(original, 0, joint_clip),
        "page 1 Joint Applicant area is unchanged",
    )
    check(
        region_text(out, 1) == region_text(original, 1),
        "page 2 (3rd Joint + For Office Use) is unchanged",
    )

    # The applicant's own values must appear ONCE on the whole document, in the
    # Primary block — never echoed into a Joint block.
    whole = squashed(out, 0) + squashed(out, 1)
    for value in ("RAJUBHAI", "SUNITA", "ANJALI", "Sinnar", "18072026"):
        check(whole.count(value) == 1, f"{value!r} appears exactly once in the document")

    print("\n--- the signature goes in the PRIMARY box only ---")
    # The detector finds five signature regions on this form (three Joint, one
    # employee); the manifest's measured rectangle must win.
    signature = next(p for p in placed if p.field_id == "applicant_signature")
    check(signature.page == 0 and signature.rect.y1 <= PRIMARY_BOTTOM,
          "signature is inside the Primary Applicant declaration")
    check(len([p for p in placed if p.field_id == "applicant_signature"]) == 1,
          "exactly one signature is drawn")

    print("\n--- fields this form does not have are reported, not guessed ---")
    reasons = {s.field_id: s.reason for s in skipped}
    for absent in ("pan", "aadhaar", "date_of_birth", "mobile", "email",
                   "correspondence_address", "city", "state", "pincode"):
        check(reasons.get(absent) == "not-on-form",
              f"{absent} reported not-on-form ({reasons.get(absent)})")
    page_all = squashed(out, 0) + squashed(out, 1)
    for value in ("CLDPP1659Q", "844587274125", "7447524240", "raju@example.com"):
        check(value not in page_all, f"{value!r} is NOT written anywhere")

    unexpected = [s for s in skipped
                  if s.reason not in ("not-on-form", "no-target", "no-region")]
    check(not unexpected, f"no unexpected skips ({[s.field_id for s in unexpected]})")

    print("\n--- geometry ---")
    collisions = [
        f"{a.field_id}x{b.field_id}"
        for i, a in enumerate(placed)
        for b in placed[i + 1:]
        if a.page == b.page and a.rect.overlaps(b.rect)
    ]
    check(not collisions, f"no overlapping placements ({collisions})")

    print("\n--- partially filled form: replace, never overprint ---")
    again = form_placement_engine.fill(
        out, dict(ANSWERS), labels, options, layout, assets={},
        asset_requirements=requirements,
    )
    check(squashed(again[0], 0).count("RAJUBHAI") == 1,
          "re-filling does not duplicate the name")
    check(sum(1 for s in again[2] if s.reason == "already-on-form") > 0,
          "unchanged values are recognised as already on the form")

    changed = form_placement_engine.fill(
        out, dict(ANSWERS, declaration_place="Nashik"), labels, options, layout,
        assets={}, asset_requirements=requirements,
    )
    swapped = squashed(changed[0], 0)
    check("Nashik" in swapped, "changed place is written")
    check("Sinnar" not in swapped, "superseded place is removed, not covered")
    check(
        region_text(changed[0], 0, joint_clip) == region_text(original, 0, joint_clip),
        "replacing a value still leaves the Joint blocks untouched",
    )

    print("\n--- occupation ticks the right box ---")
    doc = fitz.open(stream=out, filetype="pdf")
    marks = [w for w in doc[0].get_text("words") if w[4] == "X"]
    doc.close()
    check(len(marks) == 1, f"exactly one tick on the page ({len(marks)})")
    check(marks and marks[0][1] < PRIMARY_BOTTOM, "the tick is in the Primary block")
    check(marks and 110 <= marks[0][0] <= 125,
          f"the tick is on Private Sector ({marks[0][0] if marks else '-'})")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{'=' * 60}")
    print(f"AXIS: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for label in failed:
        print(f"  FAILED: {label}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
