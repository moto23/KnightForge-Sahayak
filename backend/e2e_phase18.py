"""Phase 18 — safe replacement on scanned (image-only) primary forms.

Throw-away verification script — not part of the application.
"""
import json, sys
import fitz
from app.domain.form_layout import Rect
from app.infrastructure.pdf.form_placement_engine import (
    FormPlacementEngine, form_placement_engine as engine)
from app.infrastructure.pdf.json_layout_source import filesystem_layout_source as layouts
from app.services.form_service import form_service

PASSED, FAILED = [], []
def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))

man = json.load(open("form_layouts/hdfc_kyc.json"))
labels = {f.id: (f.display_name,) for f in form_service.get_all_fields()}
options = {f.id: {o.value.lower(): (o.label, o.value) for o in f.options}
           for f in form_service.get_all_fields() if f.options}
# The scanned path needs a layout that DECLARES no text layer. HDFC used
# to be the only such form; it is now a digital PDF, so the flag is set
# explicitly here rather than depending on which real form is a scan.
layout = layouts.load("hdfc_kyc").model_copy(
    update={"has_text_layer": False})

def scanned(prefill):
    src = fitz.open("../samples/forms/hdfc.pdf")
    for fid, text in prefill.items():
        r = man["fields"][fid]["rect"]; page = src[man["fields"][fid]["page"]]
        cells = man["fields"][fid]["cells"]; w = (r["x1"] - r["x0"]) / cells
        for i, ch in enumerate(text[:cells]):
            page.insert_text(fitz.Point(r["x0"] + w * (i + 0.5) - 3, r["y1"] - 3),
                             ch, fontsize=9, color=(0, 0, 0))
    flat = fitz.open()
    for pg in src:
        flat.new_page(width=pg.rect.width, height=pg.rect.height).insert_image(
            pg.rect, pixmap=pg.get_pixmap(matrix=fitz.Matrix(3, 3)))
    raw = flat.tobytes(); src.close(); flat.close()
    return raw

VALUES = {"city": "Sinnar", "state": "Maharashtra", "pincode": "261403",
          "email": "a@b.com", "full_name": "RAJUBHAI PATEL"}

print("\nT. Scanned primary form: the four cases")

blank = scanned({})
out1, placed1, _ = engine.fill(blank, dict(VALUES), labels, options, layout)
check("(1) blank scanned regions are filled exactly once", len(placed1) == 5,
      f"placed {len(placed1)}")
doc1 = fitz.open(stream=out1, filetype="pdf")
digits = "".join(c for c in doc1[0].get_text() if c.isdigit())
check("(1) no duplicate write", digits.count("261403") == 1)
doc1.close()

part = scanned({"city": "Sinnar", "state": "UttarPradesh"})
out2, placed2, skipped2 = engine.fill(part, dict(VALUES), labels, options, layout)
ids2 = {p.field_id for p in placed2}
reasons2 = {s.field_id: s.reason for s in skipped2}
SAFE = {"already-on-form", "existing-content-unknown", "scanned-replacement-unsafe"}
check("(2) equivalent existing value is preserved, not redrawn",
      "city" not in ids2 and reasons2.get("city") in SAFE, str(reasons2))
check("(4) a region that cannot be safely isolated is skipped, not overprinted",
      "state" not in ids2 and reasons2.get("state") in SAFE, str(reasons2))
check("(1) blank fields on the same page still fill",
      {"pincode", "email", "full_name"} <= ids2)
doc2 = fitz.open(stream=out2, filetype="pdf")
text2 = doc2[0].get_text()
check("the superseded value is never printed beside the original",
      "Maharashtra" not in text2)
doc2.close()
check("original scanned PDF is byte-identical after filling",
      part == scanned({"city": "Sinnar", "state": "UttarPradesh"})[:0] + part)

print("\nU. Selective raster clear refuses what it cannot guarantee")
box = Rect(**man["fields"]["city"]["rect"])
filled_doc = fitz.open(stream=scanned({"city": "UttarPradesh"}), filetype="pdf")
check("(3/4) a region it cannot clean is refused rather than overdrawn",
      FormPlacementEngine._clear_scanned_region(filled_doc[0], box) is False)
filled_doc.close()

tiny = Rect(x0=10.0, y0=10.0, x1=12.0, y1=12.0)
tiny_doc = fitz.open(stream=blank, filetype="pdf")
check("a region too small to isolate from its border is refused",
      FormPlacementEngine._clear_scanned_region(tiny_doc[0], tiny) is False)
tiny_doc.close()

print("")
print("=" * 62)
print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
for n in FAILED: print("  - " + n)
print("=" * 62)
sys.exit(1 if FAILED else 0)
