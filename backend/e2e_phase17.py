"""Phase 17 — blank primary form must yield NO applicant values.

Regression fixtures are the five exact tested templates in samples/forms/.
Every false positive reported before the fix is asserted individually.

Throw-away verification script — not part of the application.
"""
import asyncio, io, json, sys
import fitz
from fastapi import UploadFile
from app.core.dependencies import (document_intelligence_service as dis,
    interview_service, session_service, upload_service)

PASSED, FAILED = [], []
def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))

def store(raw, name):
    return asyncio.run(upload_service.store_upload(UploadFile(
        file=io.BytesIO(raw), filename=name, headers={"content-type": "application/pdf"})))

def run(form):
    raw = open(f"../samples/forms/{form}.pdf", "rb").read()
    doc = store(raw, f"{form}.pdf")
    sid = session_service.create_session().session_id
    rep = dis.process_document(doc.document_id, sid, is_primary=True)
    prof = rep.state.documents[doc.document_id]
    return (prof.classification.schema_id,
            {v.canonical_id: v.value for v in prof.values},
            session_service.get_session(sid).answers,
            interview_service.current_progress(sid))

print("\nP. Blank primary templates produce no applicant values")
EXPECTED = {"cvl": "cvl_kyc", "sbi": "sbi_kyc", "hdfc": "hdfc_kyc",
            "icici": "icici_kyc", "axis": "axis_kyc"}
results = {}
for form, schema_id in EXPECTED.items():
    cls, values, applied, progress = run(form)
    results[form] = values
    check(f"{form}: classification still correct", cls == schema_id, cls)
    check(f"{form}: blank form yields ZERO canonical values", not values, str(values))
    check(f"{form}: nothing reaches the session as prefilled", not applied, str(applied))
    check(f"{form}: progress stays 0%", progress.progress_percentage == 0.0)

print("\nQ. Every reported false positive is gone")
for form, field, bad in (
    ("sbi", "address", "A-PASSPORT"), ("sbi", "religion", "Student"),
    ("hdfc", "address", "& CONTACT"), ("hdfc", "state", "93317/06.04.2026 M253"),
    ("icici", "name", "Prefix"), ("icici", "state", "Premise"),
    ("axis", "name", "Proof"), ("axis", "father_name", "Or"),
    ("axis", "address", "I N D I A"), ("cvl", "address", "4. Applicant Declaration"),
):
    got = results[form].get(field)
    check(f"{form}: {field} is not {bad!r}", got is None or bad.lower() not in str(got).lower(), str(got))

print("\nR. Printed option words are not treated as selections")
for form in EXPECTED:
    for choice in ("gender", "nationality", "marital_status", "occupation",
                   "residential_status", "gross_annual_income"):
        # (a field the form does not have simply cannot be auto-selected)
        check(f"{form}: {choice} not auto-selected on a blank form",
              choice not in results[form], str(results[form].get(choice)))

print("\nS. Recall on a genuinely filled form is preserved")
# ICICI is used here. Not SBI: the current SBI form (Annexure A) is a
# free-text table with no tick boxes at all. Not Axis either any more: the
# current Axis form (CK001) captures names, occupation and a declaration
# only, so it has no gender boxes to tick.
man = json.load(open("form_layouts/icici_kyc.json"))
d = fitz.open("../samples/forms/icici.pdf")
box = man["fields"]["gender"]["option_rects"]["female"]
d[0].draw_line(fitz.Point(box["x0"] + 1, box["y0"] + 1),
               fitz.Point(box["x1"] - 1, box["y1"] - 1), color=(0, 0, 0), width=1.2)
d[0].draw_line(fitz.Point(box["x1"] - 1, box["y0"] + 1),
               fitz.Point(box["x0"] + 1, box["y1"] - 1), color=(0, 0, 0), width=1.2)
filled = d.tobytes(); d.close()
doc = store(filled, "icici-ticked.pdf")
sid = session_service.create_session().session_id
rep = dis.process_document(doc.document_id, sid, is_primary=True)
got = {v.canonical_id: v.value for v in rep.state.documents[doc.document_id].values}
check("a genuinely ticked box IS detected", got.get("gender") == "female", str(got))
check("the OTHER options stay unselected", len([k for k in got if k == "gender"]) == 1)

print("")
print("=" * 62)
print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
for n in FAILED: print("  - " + n)
print("=" * 62)
sys.exit(1 if FAILED else 0)
