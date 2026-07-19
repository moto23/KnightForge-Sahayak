"""
Phase 19 persistence — the workflow must survive a backend restart.

Run in two stages so the second stage is a genuinely FRESH process, not a
re-import of warm module state:

    python e2e_restart.py build   -> creates the workflow, prints its ids
    python e2e_restart.py verify <session_id> <document_id> <pdf_id>

`python e2e_restart.py` runs both, the second in a real subprocess.
"""

import io
import json
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

RESULTS: list[tuple[bool, str]] = []
STATE = Path("_restart_state.json")


def check(ok: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


client = TestClient(app)


def register(tag: str) -> tuple[str, str]:
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    password = "Str0ng!Passw0rd"
    body = {"full_name": f"User {tag}", "email": email, "password": password}
    client.post("/auth/register", json=body)
    token = client.post(
        "/auth/login", json={"email": email, "password": password}
    ).json()["access_token"]
    return token, email


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def build() -> dict:
    """Create a real SBI workflow: session, primary form, supporting doc."""
    token_a, email_a = register("alice")
    token_b, email_b = register("bob")
    sbi = Path("../samples/forms/sbi.pdf").read_bytes()
    # Supporting evidence must NOT be another KYC form — the slot guard
    # correctly refuses that — so a plain image stands in. What is under test
    # is whether the session/document association survives a restart, not what
    # the image extracts to.
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=400, height=260)
    page.insert_text(fitz.Point(20, 40), "SUPPORTING DOCUMENT", fontsize=14)
    pan = page.get_pixmap().tobytes("png")
    doc.close()

    session = client.post("/session", headers=auth(token_a)).json()["session"]["session_id"]

    primary = client.post(
        "/upload", headers=auth(token_a),
        files={"file": ("sbi.pdf", io.BytesIO(sbi), "application/pdf")},
    ).json()["document"]["document_id"]
    client.post("/intelligence/process", headers=auth(token_a),
                json={"document_id": primary, "session_id": session, "is_primary": True})

    supporting = client.post(
        "/upload", headers=auth(token_a),
        files={"file": ("proof.png", io.BytesIO(pan), "image/png")},
    ).json()["document"]["document_id"]
    client.post("/intelligence/process", headers=auth(token_a),
                json={"document_id": supporting, "session_id": session, "is_primary": False})

    client.post(f"/session/{session}/answer", headers=auth(token_a),
                json={"field_id": "pan", "value": "CLDPP1659Q"})

    # A generated-PDF record, minted directly: generating through the API needs
    # a COMPLETE interview, and what is under test is whether the record and its
    # session survive a restart.
    from datetime import datetime, timezone
    from app.core.dependencies import _generated_pdf_repository
    from app.domain.pdf import GeneratedPdf
    from app.core.config import settings

    pdf_id = uuid.uuid4().hex
    # Through the FileStorage port, matching the service: in production these
    # bytes live in a private bucket, not on the instance disk.
    from app.core.dependencies import _file_storage
    from app.domain.enums import DocumentCategory
    _file_storage.save(DocumentCategory.PDF, f"{pdf_id}.pdf", sbi)
    _generated_pdf_repository.add(GeneratedPdf(
        pdf_id=pdf_id, stored_filename=f"{pdf_id}.pdf",
        generated_by_session=session, template_id="sbi_kyc", template_version="1",
        fields_filled=1, file_size=len(sbi), page_count=1,
        generated_at=datetime.now(timezone.utc), answers_fingerprint="test",
    ))

    profile = client.get(f"/intelligence/profile/{session}", headers=auth(token_a)).json()
    progress = client.get(f"/session/{session}/progress", headers=auth(token_a)).json()

    state = {
        "session": session, "primary": primary, "supporting": supporting,
        "pdf_id": pdf_id,
        "email_a": email_a, "email_b": email_b, "password": "Str0ng!Passw0rd",
        "form_id": (profile.get("primary_form") or {}).get("schema_id"),
        "form_label": (profile.get("primary_form") or {}).get("label"),
        "value_count": len(profile.get("fields") or []),
        "progress": progress.get("progress_percentage"),
    }
    print("\n--- built ---")
    print("  active form :", state["form_id"], "|", state["form_label"])
    print("  documents   :", state["primary"][:8], state["supporting"][:8])
    print("  progress    :", state["progress"])
    return state


def login(email: str, password: str) -> str:
    return client.post("/auth/login", json={"email": email, "password": password}
                       ).json()["access_token"]


def verify(state: dict) -> int:
    """Fresh process: everything must still be there, and still isolated."""
    session = state["session"]
    token_a = login(state["email_a"], state["password"])
    token_b = login(state["email_b"], state["password"])

    print("\n--- the session itself survived ---")
    got = client.get(f"/session/{session}", headers=auth(token_a))
    check(got.status_code == 200, f"session restores after restart ({got.status_code})")
    body = got.json()
    body = body.get("session", body)
    check(body.get("answers", {}).get("pan") == "CLDPP1659Q",
          "the answer given before the restart is still there")

    print("\n--- SBI is still the active form ---")
    profile = client.get(f"/intelligence/profile/{session}", headers=auth(token_a))
    check(profile.status_code == 200, f"profile restores ({profile.status_code})")
    pdata = profile.json()
    active = pdata.get("primary_form") or {}
    check(active.get("schema_id") == state["form_id"] == "sbi_kyc",
          f"active primary form is still sbi_kyc ({active.get('schema_id')})")
    check(active.get("label") == state["form_label"], "the form label is unchanged")

    print("\n--- documents, evidence and profile values persist ---")
    values = pdata.get("fields") or []
    check(len(values) == state["value_count"],
          f"merged canonical values persist ({len(values)} vs {state['value_count']})")
    check(len(pdata.get("documents") or []) == 2,
          f"both documents are still attached ({len(pdata.get('documents') or [])})")
    for label, doc_id in (("primary", state["primary"]), ("supporting", state["supporting"])):
        meta = client.get(f"/upload/{doc_id}", headers=auth(token_a))
        check(meta.status_code == 200, f"{label} document metadata restores ({meta.status_code})")
        raw = client.get(f"/upload/{doc_id}/file", headers=auth(token_a))
        check(raw.status_code == 200, f"{label} document file still resolves ({raw.status_code})")

    print("\n--- Progress and AI-Guided Completion resume ---")
    progress = client.get(f"/session/{session}/progress", headers=auth(token_a))
    check(progress.status_code == 200, "progress endpoint answers")
    check(progress.json().get("progress_percentage") == state["progress"],
          f"progress is unchanged ({progress.json().get('progress_percentage')} "
          f"vs {state['progress']})")
    check(progress.json().get("progress_percentage") not in (None, 0.0)
          or state["progress"] in (None, 0.0),
          "progress did not collapse to 0%")
    nxt = client.get(f"/session/{session}/next", headers=auth(token_a))
    check(nxt.status_code == 200, f"the interview resumes ({nxt.status_code})")

    print("\n--- the generated PDF still resolves ---")
    meta = client.get(f"/pdf/{state['pdf_id']}", headers=auth(token_a))
    check(meta.status_code == 200, f"PDF metadata restores ({meta.status_code})")
    dl = client.get(f"/pdf/{state['pdf_id']}/download", headers=auth(token_a))
    check(dl.status_code == 200, f"PDF download still resolves ({dl.status_code})")

    print("\n--- no phantom or cross-session documents ---")
    scoped = client.get(f"/upload?session_id={session}", headers=auth(token_a))
    ids = {d["document_id"] for d in scoped.json()["documents"]}
    check(ids == {state["primary"], state["supporting"]},
          f"the session lists exactly its own two documents ({len(ids)})")
    other = client.post("/session", headers=auth(token_a)).json()["session"]["session_id"]
    fresh = client.get(f"/upload?session_id={other}", headers=auth(token_a))
    check(fresh.json()["documents"] == [],
          "a new session starts with no documents (no phantom carry-over)")

    print("\n--- User A/B isolation survived the restart ---")
    for label, url in (("session", f"/session/{session}"),
                       ("profile", f"/intelligence/profile/{session}"),
                       ("document", f"/upload/{state['primary']}"),
                       ("document file", f"/upload/{state['primary']}/file"),
                       ("PDF", f"/pdf/{state['pdf_id']}"),
                       ("PDF download", f"/pdf/{state['pdf_id']}/download")):
        r = client.get(url, headers=auth(token_b))
        check(r.status_code in (403, 404), f"User B still refused: {label} ({r.status_code})")
        anon = client.get(url)
        check(anon.status_code in (403, 404),
              f"anonymous still refused: {label} ({anon.status_code})")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{'=' * 60}")
    print(f"RESTART: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for label in failed:
        print(f"  FAILED: {label}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    if mode == "build":
        STATE.write_text(json.dumps(build()), encoding="utf-8")
        sys.exit(0)
    if mode == "verify":
        sys.exit(verify(json.loads(STATE.read_text(encoding="utf-8"))))
    # both: build here, verify in a genuinely fresh interpreter
    STATE.write_text(json.dumps(build()), encoding="utf-8")
    print("\n=== restarting backend (new process) ===")
    sys.exit(subprocess.call([sys.executable, __file__, "verify"]))
