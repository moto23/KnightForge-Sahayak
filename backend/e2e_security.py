"""
Phase 19 — cross-user isolation and deployment-safety regression tests.

The finding these pin: a session holds the applicant's PAN, Aadhaar, date of
birth, address, photograph and signature, and every asset and generated PDF
hangs off it. Before this pass the only thing between one applicant's KYC data
and another's was the secrecy of a UUID in a URL — no endpoint checked who was
asking. User B could read, re-fill, download and delete User A's KYC session by
substituting the id.

Usage:  python e2e_security.py
"""

import io
import pathlib
import sys
import uuid

import fitz
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


client = TestClient(app)


def register(tag: str) -> str:
    """Create a user and return its bearer token."""
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    body = {"full_name": f"User {tag}", "email": email, "password": "Str0ng!Passw0rd"}
    response = client.post("/auth/register", json=body)
    if response.status_code >= 400:
        response = client.post("/auth/login",
                               json={"email": email, "password": body["password"]})
    data = response.json()
    return data.get("access_token") or data.get("token") or ""


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def png(w: int, h: int) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    page.draw_rect(fitz.Rect(0, 0, w, h), color=(1, 0, 0), fill=(1, 0, 0))
    raw = page.get_pixmap().tobytes("png")
    doc.close()
    return raw


def main() -> int:
    print("\n--- two separate accounts ---")
    token_a = register("alice")
    token_b = register("bob")
    check(bool(token_a) and bool(token_b), "both users registered and hold tokens")
    check(token_a != token_b, "the two tokens differ")

    print("\n--- User A creates a KYC session and fills it ---")
    created = client.post("/session", headers=auth(token_a))
    check(created.status_code in (200, 201), f"session created ({created.status_code})")
    session_a = created.json()["session"]["session_id"]

    answered = client.post(
        f"/session/{session_a}/answer",
        headers=auth(token_a),
        json={"field_id": "pan", "value": "CLDPP1659Q"},
    )
    check(answered.status_code == 200, f"User A can answer their own session ({answered.status_code})")

    uploaded = client.post(
        f"/assets/{session_a}/photo",
        headers=auth(token_a),
        files={"file": ("photo.png", io.BytesIO(png(150, 190)), "image/png")},
    )
    check(uploaded.status_code in (200, 201, 400, 409, 422),
          f"asset upload endpoint answers User A ({uploaded.status_code})")

    print("\n--- User B may NOT touch User A's session ---")
    # Every one of these leaks or destroys KYC data if it succeeds.
    attacks = [
        ("GET  session", client.get, f"/session/{session_a}", None),
        ("GET  progress", client.get, f"/session/{session_a}/progress", None),
        ("GET  next question", client.get, f"/session/{session_a}/next", None),
        ("GET  assets", client.get, f"/assets/{session_a}", None),
        ("GET  photo file", client.get, f"/assets/{session_a}/photo/file", None),
        ("GET  profile", client.get, f"/intelligence/profile/{session_a}", None),
    ]
    for label, method, url, body in attacks:
        response = method(url, headers=auth(token_b))
        check(response.status_code in (403, 404),
              f"User B is refused: {label} ({response.status_code})",
              f"{response.status_code} {response.text[:120]}")

    writes = [
        ("POST answer", client.post, f"/session/{session_a}/answer",
         {"field_id": "pan", "value": "ZZZZZ9999Z"}),
    ]
    for label, method, url, body in writes:
        response = method(url, headers=auth(token_b), json=body)
        check(response.status_code in (403, 404),
              f"User B is refused: {label} ({response.status_code})",
              f"{response.status_code} {response.text[:120]}")

    deleted = client.delete(f"/assets/{session_a}/photo", headers=auth(token_b))
    check(deleted.status_code in (403, 404),
          f"User B cannot delete User A's photograph ({deleted.status_code})")
    dropped = client.delete(f"/session/{session_a}", headers=auth(token_b))
    check(dropped.status_code in (403, 404),
          f"User B cannot delete User A's session ({dropped.status_code})")

    print("\n--- a guest with no token is refused too ---")
    for label, url in (("session", f"/session/{session_a}"),
                       ("assets", f"/assets/{session_a}")):
        response = client.get(url)
        check(response.status_code in (403, 404),
              f"an anonymous caller is refused: {label} ({response.status_code})")

    print("\n--- and User A still has full access ---")
    mine = client.get(f"/session/{session_a}", headers=auth(token_a))
    check(mine.status_code == 200, f"User A can still read their session ({mine.status_code})")
    body_a = mine.json()
    body_a = body_a.get("session", body_a)
    check(body_a.get("answers", {}).get("pan") == "CLDPP1659Q",
          "User A's answer survived every rejected attack")

    print("\n--- refusal does not confirm the id exists ---")
    unknown = client.get(f"/session/{uuid.uuid4().hex}", headers=auth(token_b))
    stolen = client.get(f"/session/{session_a}", headers=auth(token_b))
    check(unknown.status_code == stolen.status_code,
          f"an unknown id and someone else's id answer alike "
          f"({unknown.status_code} vs {stolen.status_code})")

    print("\n--- guest sessions still work, and are claimed on sign-in ---")
    guest = client.post("/session")
    check(guest.status_code in (200, 201), f"a guest can create a session ({guest.status_code})")
    guest_id = guest.json()["session"]["session_id"]
    check(client.get(f"/session/{guest_id}").status_code == 200,
          "the guest can read their own session")
    claimed = client.get(f"/session/{guest_id}", headers=auth(token_a))
    check(claimed.status_code == 200, "a signed-in user may claim an unowned session")
    check(client.get(f"/session/{guest_id}", headers=auth(token_b)).status_code in (403, 404),
          "once claimed, another user is locked out")

    print("\n--- User A's uploaded DOCUMENT is private ---")
    pdf_bytes = open("../samples/forms/cvl.pdf", "rb").read()
    up = client.post(
        "/upload",
        headers=auth(token_a),
        files={"file": ("cvl.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    check(up.status_code in (200, 201), f"User A uploaded a KYC form ({up.status_code})")
    doc_body = up.json()
    doc_id = (doc_body.get("document") or doc_body).get("document_id")
    check(bool(doc_id), "the upload returned a document id")

    for label, method in (("GET metadata", client.get), ("DELETE", client.delete)):
        response = method(f"/upload/{doc_id}", headers=auth(token_b))
        check(response.status_code in (403, 404),
              f"User B is refused the document: {label} ({response.status_code})")
    for label, url in (("file", f"/upload/{doc_id}/file"),):
        response = client.get(url, headers=auth(token_b))
        check(response.status_code in (403, 404),
              f"User B is refused the document {label} ({response.status_code})")
        check(client.get(url).status_code in (403, 404),
              f"an anonymous caller is refused the document {label}")
    check(client.get(f"/upload/{doc_id}", headers=auth(token_a)).status_code == 200,
          "User A still reads their own document")

    print("\n--- User A's generated PDF is private ---")
    # Generating through the API needs a COMPLETE interview, which is not
    # what is under test here — the authorisation layer is. So a record is
    # minted directly for User A's session and then attacked over HTTP.
    from app.core.dependencies import _generated_pdf_repository
    from app.domain.pdf import GeneratedPdf
    from datetime import datetime, timezone
    pdf_id = uuid.uuid4().hex
    # Write through the SAME FileStorage port the service uses, not straight to
    # a directory: generated PDFs live in object storage in production, and a
    # fixture that hardcodes a local path tests a location the product no
    # longer writes to.
    from app.core.dependencies import _file_storage
    from app.domain.enums import DocumentCategory
    _file_storage.save(DocumentCategory.PDF, f"{pdf_id}.pdf", pdf_bytes)
    _generated_pdf_repository.add(GeneratedPdf(
        pdf_id=pdf_id,
        stored_filename=f"{pdf_id}.pdf",
        generated_by_session=session_a,
        template_id="cvl_kyc",
        template_version="1",
        fields_filled=1,
        file_size=len(pdf_bytes),
        generated_at=datetime.now(timezone.utc),
        answers_fingerprint="test",
        page_count=1,
    ))
    check(True, "a PDF record exists for User A's session")

    if pdf_id:
        for label, method, url in (
            ("metadata", client.get, f"/pdf/{pdf_id}"),
            ("download", client.get, f"/pdf/{pdf_id}/download"),
            ("delete", client.delete, f"/pdf/{pdf_id}"),
        ):
            response = method(url, headers=auth(token_b))
            check(response.status_code in (403, 404),
                  f"User B is refused the PDF {label} ({response.status_code})")
            anon = method(url)
            check(anon.status_code in (403, 404),
                  f"an anonymous caller is refused the PDF {label} ({anon.status_code})")
        check(client.get(f"/pdf/{pdf_id}", headers=auth(token_a)).status_code == 200,
              "User A still reads their own PDF")
        check(client.get(f"/pdf/{pdf_id}/download", headers=auth(token_a)).status_code == 200,
              "User A still downloads their own PDF")

    # PDF history must be per-user, not the whole deployment's.
    b_history = client.get("/pdf", headers=auth(token_b))
    if b_history.status_code == 200 and pdf_id:
        ids = [r.get("pdf_id") for r in b_history.json()]
        check(pdf_id not in ids, "User A's PDF does not appear in User B's history")

    print("\n--- User A's CONVERSATION is private ---")
    for label, url, payload in (
        ("reply", "/conversation/reply", {"session_id": session_a, "message": "hi"}),
        ("explain", "/conversation/explain", {"session_id": session_a}),
        ("extract", "/conversation/extract",
         {"session_id": session_a, "message": "my pan is CLDPP1659Q"}),
    ):
        response = client.post(url, headers=auth(token_b), json=payload)
        check(response.status_code in (403, 404, 422),
              f"User B is refused conversation/{label} ({response.status_code})")
        check(response.status_code != 200,
              f"conversation/{label} did not serve User B")

    print("\n--- User A's INTELLIGENCE pipeline is private ---")
    # These three take session_id in the BODY and every one of them MUTATES the
    # session: /process writes extracted values into it, /primary-form rescopes
    # the whole questionnaire, /resolve overwrites a disputed canonical value.
    intel_attacks = (
        ("process", "/intelligence/process",
         {"document_id": doc_id, "session_id": session_a, "is_primary": True}),
        ("primary-form", "/intelligence/primary-form",
         {"session_id": session_a, "form_id": "cvl_kyc"}),
        ("resolve", "/intelligence/resolve",
         {"session_id": session_a, "canonical_id": "pan", "value": "ZZZZZ9999Z"}),
    )
    for label, url, payload in intel_attacks:
        as_b = client.post(url, headers=auth(token_b), json=payload)
        check(as_b.status_code in (403, 404),
              f"User B is refused intelligence/{label} ({as_b.status_code})")
        check(as_b.status_code != 200, f"intelligence/{label} did not serve User B")
        anon = client.post(url, json=payload)
        check(anon.status_code in (403, 404),
              f"an anonymous caller is refused intelligence/{label} ({anon.status_code})")
        check(anon.status_code != 200,
              f"intelligence/{label} did not serve an anonymous caller")

    # The refusals must have changed nothing: User A's PAN is still their own.
    after = client.get(f"/session/{session_a}", headers=auth(token_a))
    after_body = after.json()
    after_body = after_body.get("session", after_body)
    check(after_body.get("answers", {}).get("pan") == "CLDPP1659Q",
          "User A's answers are untouched by the refused intelligence calls")

    # And User A can still drive their own pipeline.
    own = client.post("/intelligence/primary-form", headers=auth(token_a),
                      json={"session_id": session_a, "form_id": "cvl_kyc"})
    check(own.status_code == 200,
          f"User A can still set their own primary form ({own.status_code})")

    print("\n--- a document belonging to another user cannot be pulled in ---")
    # User B owns a session of their own AND their own document. The attack is
    # not against B's session — it is B naming A's document_id inside B's OWN
    # session, which would extract A's PAN/Aadhaar into B's profile.
    b_session = client.post("/session", headers=auth(token_b)).json()["session"]["session_id"]
    b_upload = client.post(
        "/upload",
        headers=auth(token_b),
        files={"file": ("bob.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    b_doc = (b_upload.json().get("document") or b_upload.json()).get("document_id")
    check(bool(b_doc), "User B has a document of their own")

    def profile_of(session_id: str, token: str):
        """
        The profile's DATA, with `updated_at` dropped.

        Reading the profile re-syncs it, so `updated_at` moves on every read —
        including the two reads this comparison itself performs. Comparing it
        would report a mutation that the measurement caused. Everything that
        carries applicant data is still compared exactly.
        """
        response = client.get(f"/intelligence/profile/{session_id}", headers=auth(token))
        if response.status_code != 200:
            return None
        return {k: v for k, v in response.json().items() if k != "updated_at"}

    before_b = profile_of(b_session, token_b)

    stolen = client.post(
        "/intelligence/process",
        headers=auth(token_b),
        json={"document_id": doc_id, "session_id": b_session, "is_primary": True},
    )
    check(stolen.status_code in (403, 404),
          f"User B cannot process User A's document into B's own session "
          f"({stolen.status_code})")
    check(stolen.status_code != 200, "the theft attempt was not served")

    anon_steal = client.post(
        "/intelligence/process",
        json={"document_id": doc_id, "session_id": b_session, "is_primary": True},
    )
    check(anon_steal.status_code in (403, 404),
          f"an anonymous caller cannot process User A's document ({anon_steal.status_code})")

    resolve_steal = client.post(
        "/intelligence/resolve",
        headers=auth(token_b),
        json={"session_id": b_session, "canonical_id": "pan", "document_id": doc_id},
    )
    check(resolve_steal.status_code in (403, 404),
          f"User B cannot resolve from User A's document ({resolve_steal.status_code})")

    # ZERO mutation: B's own session and profile must be exactly as before.
    check(profile_of(b_session, token_b) == before_b,
          "User B's profile is byte-identical after every refused call")
    b_session_body = client.get(f"/session/{b_session}", headers=auth(token_b)).json()
    b_session_body = b_session_body.get("session", b_session_body)
    check(not b_session_body.get("answers"),
          f"User B's session gained no answers ({b_session_body.get('answers')})")
    check("CLDPP1659Q" not in str(b_session_body),
          "no value from User A's document leaked into User B's session")

    # User B may still use their OWN document in their OWN session.
    legit = client.post(
        "/intelligence/process",
        headers=auth(token_b),
        json={"document_id": b_doc, "session_id": b_session, "is_primary": True},
    )
    check(legit.status_code == 200,
          f"User B can still process their own document ({legit.status_code})")

    print("\n--- rate limiting ---")
    from app.core.rate_limit import auth_limiter, upload_limiter
    auth_limiter.reset()
    codes = [
        client.post("/auth/login",
                    json={"email": "nobody@example.com", "password": "wrong"}).status_code
        for _ in range(auth_limiter.limit + 3)
    ]
    check(429 in codes, f"repeated failed logins are throttled ({sorted(set(codes))})")
    auth_limiter.reset()
    check(client.post("/auth/login",
                      json={"email": "nobody@example.com", "password": "wrong"}
                      ).status_code != 429,
          "the window reopens after a reset")

    # A normal multi-file upload burst must NOT be throttled.
    upload_limiter.reset()
    burst = [
        client.post("/upload", headers=auth(token_a),
                    files={"file": (f"doc{i}.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
                    ).status_code
        for i in range(8)
    ]
    check(429 not in burst, f"an 8-file upload burst is not throttled ({sorted(set(burst))})")

    print("\n--- deployment configuration ---")
    from app.core.config import Settings
    # An unsafely configured production process must refuse to start.
    for unsafe, label in (
        ({}, "shipped JWT secret"),
        ({"JWT_SECRET": "short", "DEBUG": False}, "JWT secret under 32 bytes"),
        ({"JWT_SECRET": "x" * 44}, "DEBUG left on"),
        ({"JWT_SECRET": "x" * 44, "DEBUG": False, "CORS_ORIGINS": "*"}, "CORS wildcard"),
        ({"JWT_SECRET": "x" * 44, "DEBUG": False,
          "CORS_ORIGINS": "http://app.example.com"}, "plain-http origin"),
        # Durability: these do not fail loudly in production, they lose
        # applicant data quietly at the next redeploy.
        ({"JWT_SECRET": "x" * 44, "DEBUG": False,
          "CORS_ORIGINS": "https://sahayak.example.com",
          "STORAGE_BACKEND": "s3", "STORAGE_BUCKET": "b",
          "STORAGE_ENDPOINT_URL": "https://e", "STORAGE_ACCESS_KEY_ID": "k",
          "STORAGE_SECRET_ACCESS_KEY": "s"}, "SQLite database"),
        ({"JWT_SECRET": "x" * 44, "DEBUG": False,
          "CORS_ORIGINS": "https://sahayak.example.com",
          "DATABASE_URL": "postgresql+psycopg://u:p@h/db"}, "local file storage"),
        ({"JWT_SECRET": "x" * 44, "DEBUG": False,
          "CORS_ORIGINS": "https://sahayak.example.com",
          "DATABASE_URL": "postgresql+psycopg://u:p@h/db",
          "STORAGE_BACKEND": "s3"}, "s3 storage without credentials"),
    ):
        try:
            Settings(ENVIRONMENT="production", _env_file=None, **unsafe)
            check(False, f"production refuses to boot with: {label}")
        except Exception:
            check(True, f"production refuses to boot with: {label}")
    try:
        Settings(ENVIRONMENT="production", DEBUG=False, JWT_SECRET="x" * 44,
                 CORS_ORIGINS="https://sahayak.example.com",
                 DATABASE_URL="postgresql+psycopg://u:p@h/db",
                 STORAGE_BACKEND="s3", STORAGE_BUCKET="kyc-files",
                 STORAGE_ENDPOINT_URL="https://example.storage",
                 STORAGE_ACCESS_KEY_ID="key", STORAGE_SECRET_ACCESS_KEY="secret",
                 _env_file=None)
        check(True, "a correctly configured production boots")
    except Exception as exc:
        check(False, f"a correctly configured production boots ({exc})")
    check("*" not in settings.cors_origins_list, "CORS does not allow every origin")
    check(settings.ENVIRONMENT != "production" or not settings.DEBUG,
          "local development is unaffected by the production guard")
    health = client.get("/health")
    check(health.status_code == 200, f"health endpoint responds ({health.status_code})")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{'=' * 60}")
    print(f"SECURITY: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for label in failed:
        print(f"  FAILED: {label}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
