"""
Render every supported KYC form with a full set of answers, then report and
rasterise the result for VISUAL inspection.

This is the check that unit tests cannot make. The previous engine passed its
tests while producing a page with the date of birth and mobile number printed
on top of each other — a defect only visible by looking at the page.

Usage:  python render_forms.py [form ...]
Output: samples/rendered/<form>-p<N>.png  plus a placement report per form.

Throw-away verification tool — not part of the application.
"""

import sys
from pathlib import Path

import fitz

from app.domain.form_assets import AssetKind, FormAssetRequirements
from app.infrastructure.pdf.form_placement_engine import form_placement_engine
from app.infrastructure.pdf.json_layout_source import filesystem_layout_source
from app.services.form_asset_detector import form_asset_detector
from app.services.form_service import form_service

FORMS = {
    "cvl": "cvl_kyc",
    "sbi": "sbi_kyc",
    "hdfc": "hdfc_kyc",
    "icici": "icici_kyc",
    "axis": "axis_kyc",
}

# Realistic answers. Deliberately includes a long address and a long email, so
# overflow into neighbouring fields would be obvious rather than marginal.
ANSWERS = {
    "full_name": "RAJUBHAI SAHEBLAL PATEL",
    "father_spouse_name": "SAHEBLAL BABASO PATEL",
    "date_of_birth": "01-01-1966",
    "gender": "male",
    "marital_status": "married",
    "nationality": "indian",
    "residential_status": "resident_individual",
    "pan": "CLDPP1659Q",
    "aadhaar": "844587274125",
    "address_line1": "Flat 402 Shreeji Residency, Post Baratal, Majra Gopalpur",
    "correspondence_address": "Flat 402 Shreeji Residency, Post Baratal",
    "account_number": "30123456789",
    "ckycr_number": "12345678901234",
    "mother_name": "SUNITA PATEL",
    "spouse_name": "ANJALI PATEL",
    "religion": "Hindu",
    "category": "general",
    "monthly_income": "45000",
    "city": "Sitapur",
    "district": "Sitapur",
    "state": "Uttar Pradesh",
    "pincode": "261403",
    "country": "India",
    "mobile": "7447524240",
    "email": "rajubhai.saheblal.patel@example.com",
    "occupation": "private_sector",
    "gross_annual_income": "1_5l",
    "declaration_place": "Sinnar",
    "declaration_date": "18-07-2026",
}


def image(width: int, height: int, rgb: tuple[float, float, float]) -> bytes:
    document = fitz.open()
    page = document.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(0, 0, width, height), color=rgb, fill=rgb)
    raw = page.get_pixmap().tobytes("png")
    document.close()
    return raw


PHOTO = image(150, 190, (0.85, 0.2, 0.2))
SIGNATURE = image(240, 60, (0.1, 0.45, 0.15))


def vocabulary():
    """field id -> printed captions, from the interview registry."""
    labels, options = {}, {}
    for field in form_service.get_all_fields():
        labels[field.id] = (field.display_name,)
        if field.options:
            options[field.id] = {
                o.value.lower(): (o.label, o.value) for o in field.options
            }
    return labels, options


def overlaps_report(placed) -> list[str]:
    """Every pair of placed rectangles that intersect — must be empty."""
    problems = []
    for i, a in enumerate(placed):
        for b in placed[i + 1 :]:
            if a.page == b.page and a.rect.overlaps(b.rect):
                problems.append(f"{a.field_id} x {b.field_id} (page {a.page + 1})")
    return problems


def run(name: str) -> bool:
    source_path = Path(f"../samples/forms/{name}.pdf")
    raw = source_path.read_bytes()
    layout = filesystem_layout_source.load(FORMS[name])
    labels, options = vocabulary()

    requirements: FormAssetRequirements | None = form_asset_detector.detect(raw)

    out, placed, skipped = form_placement_engine.fill(
        raw, dict(ANSWERS), labels, options, layout,
        assets={AssetKind.PHOTO: PHOTO, AssetKind.SIGNATURE: SIGNATURE},
        asset_requirements=requirements,
    )

    collisions = overlaps_report(placed)
    print(f"\n=== {name.upper()} ({FORMS[name]}) ===")
    print(f"  manifest: {'yes' if layout else 'NO'}"
          f"{' (no text layer)' if layout and not layout.has_text_layer else ''}")
    print(f"  placed : {len(placed)}")
    for p in placed:
        print(f"     p{p.page + 1} {p.field_id:22} {p.source.value:14}"
              f" ({p.rect.x0:5.0f},{p.rect.y0:5.0f})-({p.rect.x1:5.0f},{p.rect.y1:5.0f})")
    print(f"  skipped: {len(skipped)}  {[f'{s.field_id}:{s.reason}' for s in skipped]}")
    print(f"  OVERLAPS: {collisions if collisions else 'none'}")

    # Original must be untouched.
    assert source_path.read_bytes() == raw, "source PDF was modified!"

    out_dir = Path("../samples/rendered")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}-filled.pdf").write_bytes(out)
    document = fitz.open(stream=out, filetype="pdf")
    pages_with_content = {p.page for p in placed}
    for pno in sorted(pages_with_content) or [0]:
        pix = document[pno].get_pixmap(dpi=110)
        pix.save(out_dir / f"{name}-p{pno + 1}.png")
    document.close()
    return not collisions


if __name__ == "__main__":
    targets = sys.argv[1:] or list(FORMS)
    ok = all(run(t) for t in targets)
    print(f"\n{'=' * 60}\n{'NO OVERLAPS ON ANY FORM' if ok else 'OVERLAPS DETECTED'}\n{'=' * 60}")
    sys.exit(0 if ok else 1)
