"""Phase 11 E2E verification against the LIVE backend (http://127.0.0.1:8000).

Generates digital sample PDFs (PAN card, Aadhaar, filled CVL form, filled SBI
form), then drives both demo flows over real HTTP:

    Demo 1: PAN + Aadhaar + CVL  ->  classify, extract, merge, conflict,
            resolve, interview asks only missing, generate final PDF
    Demo 2: PAN + Aadhaar + SBI  ->  the EXACT same pipeline, different schema

Throw-away verification script — not part of the application.
"""

import json
import mimetypes
import tempfile
import urllib.request
import uuid
from pathlib import Path

import fitz  # PyMuPDF — already a backend dependency

BASE = "http://127.0.0.1:8000"

PAN_TEXT = """INCOME TAX DEPARTMENT       GOVT. OF INDIA
Permanent Account Number Card
FMPPN2545Q
Name
PRASAD NATHE
Father's Name
RAMESH NATHE
Date of Birth
15/08/1999"""

AADHAAR_TEXT = """Government of India
Unique Identification Authority of India
Your Aadhaar No. : 9999 4105 7058
PRASAD N NATHE
DOB: 15/08/1999
MALE
Address: Flat 302 MG Road Pune Maharashtra 411001
Mera Aadhaar, Meri Pehchan"""

CVL_TEXT = """Know Your Client (KYC) Application Form (For Individuals Only)
A. Identity Details
Name of Applicant  PRASAD NATHE
Father's/Spouse Name  RAMESH NATHE
Gender Male
Date of Birth 15-08-1999
Nationality Indian
PAN FMPPN2545Q
B. Address Details
Address for Correspondence  FLAT 302 MG ROAD PUNE
City/Town/Village PUNE
State MAHARASHTRA
Pin Code 411001
Mobile 9876543210
E-Mail ID prasad@example.com
C. Other Details
Gross Annual Income 10-25 Lac
Occupation Private Sector Service"""

SBI_TEXT = """STATE BANK OF INDIA
Know Your Customer (KYC) Application Form
Customer Name  PRASAD NATHE
Father's Name  RAMESH NATHE
Date of Birth 15-08-1999
Gender Male
PAN FMPPN2545Q
Communication Address  FLAT 302 MG ROAD
City PUNE
State MAHARASHTRA
Pin Code 411001
Mobile No 9876543210
E-Mail ID prasad@example.com
Occupation Private Sector Service
Gross Annual Income 10-25 Lac"""


def make_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 60), text, fontsize=11)
    doc.save(path)
    doc.close()


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def upload(path: Path) -> str:
    boundary = uuid.uuid4().hex
    content = path.read_bytes()
    ctype = mimetypes.guess_type(path.name)[0] or "application/pdf"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{path.name}\"\r\nContent-Type: {ctype}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/upload",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["document"]["document_id"]


def run_demo(name: str, files: list[Path]) -> None:
    print(f"\n{'=' * 70}\nDEMO: {name}\n{'=' * 70}")
    session_id = call("POST", "/session")["session"]["session_id"]

    profile = None
    for path in files:
        doc_id = upload(path)
        result = call(
            "POST", "/intelligence/process",
            {"document_id": doc_id, "session_id": session_id},
        )
        dt = result["document"]["document_type"]
        print(
            f"  {path.name:14} -> {dt['label']:22} (schema={dt['schema_id']}, "
            f"conf={dt['confidence']}) values={len(result['document']['values'])} "
            f"applied={result['applied_from_document']}"
        )
        profile = result["profile"]

    print(f"\n  merge_status = {profile['merge_status']}")
    print(f"  progress     = {profile['progress_percentage']}%")
    for f in profile["fields"]:
        print(
            f"    {f['label']:26} = {f['value']!r:44} "
            f"[{f['source_type_label']}] applied={f['applied']}"
        )
    open_conflicts = [c for c in profile["conflicts"] if not c["resolved"]]
    for c in open_conflicts:
        print(f"\n  CONFLICT on {c['label']}:")
        for o in c["options"]:
            print(f"    {o['document_type_label']:14} -> {o['value']!r}")
        # Resolve by choosing the FIRST (best-evidence) option.
        profile = call(
            "POST", "/intelligence/resolve",
            {
                "session_id": session_id,
                "canonical_id": c["canonical_id"],
                "document_id": c["options"][0]["document_id"],
            },
        )
        print(f"  resolved -> merge_status={profile['merge_status']}, "
              f"progress={profile['progress_percentage']}%")

    # Interview asks ONLY missing fields.
    nxt = call("GET", f"/session/{session_id}/next")
    answered = call("GET", f"/session/{session_id}")["answers"]
    print(f"\n  answers in session: {len(answered)}")
    print(
        f"  interview: remaining_required={nxt['remaining_required']}, "
        f"next question = {(nxt['question'] or {}).get('id')}"
    )

    # Fill whatever is still required so the PDF can be generated.
    fill = {
        "marital_status": "single", "residential_status": "resident_individual",
        "nationality": "indian", "country": "India", "poa_document": "passport",
        "is_pep": "no", "is_pep_related": "no",
        "declaration_place": "Pune", "declaration_date": "15-07-2026",
        "correspondence_address": "FLAT 302 MG ROAD PUNE",
        "occupation": "private_sector", "gross_annual_income": "10_25l",
        "gender": "male", "city": "Pune", "state": "Maharashtra",
        "pincode": "411001", "mobile": "9876543210",
        "full_name": "PRASAD NATHE", "father_spouse_name": "RAMESH NATHE",
        "date_of_birth": "15-08-1999", "pan": "FMPPN2545Q",
    }
    while True:
        nxt = call("GET", f"/session/{session_id}/next")
        if nxt["completed"] or not nxt["question"]:
            break
        fid = nxt["question"]["id"]
        value = fill.get(fid)
        if value is None:
            print(f"  !! no scripted answer for {fid} — stopping fill loop")
            break
        call("POST", f"/session/{session_id}/answer", {"field_id": fid, "value": value})

    pdf = call("POST", "/pdf/generate", {"session_id": session_id})
    info = pdf.get("pdf") or pdf
    print(f"\n  FINAL PDF generated: {json.dumps(info)[:160]}")


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    pan, aadhaar = tmp / "pan-card.pdf", tmp / "aadhaar-card.pdf"
    cvl, sbi = tmp / "cvl-form.pdf", tmp / "sbi-form.pdf"
    make_pdf(pan, PAN_TEXT)
    make_pdf(aadhaar, AADHAAR_TEXT)
    make_pdf(cvl, CVL_TEXT)
    make_pdf(sbi, SBI_TEXT)

    run_demo("1 — PAN + Aadhaar + CVL", [pan, aadhaar, cvl])
    run_demo("2 — PAN + Aadhaar + SBI (same pipeline, different schema)", [pan, aadhaar, sbi])
    print("\nALL DEMO FLOWS COMPLETED")


if __name__ == "__main__":
    main()
