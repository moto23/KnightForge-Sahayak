"""
Live production smoke test — runs against the DEPLOYED backend over HTTPS.

Everything here talks to the real service: real Postgres, real object storage,
real OCR. It creates two throwaway accounts and exercises the pipeline the way
a user does, then checks the things that only break in production — ownership
across users, persistence across a restart, and whether stored bytes actually
come back.

Usage:
    python smoke_live.py https://<backend-host>
    python smoke_live.py https://<backend-host> --restart-check

`--restart-check` re-reads state written by a PREVIOUS run (ids are kept in
smoke_state.json) to prove a redeploy did not lose it.
"""

import io
import json
import sys
import uuid
from pathlib import Path

import httpx

RESULTS: list[tuple[bool, str]] = []
STATE = Path("smoke_state.json")


def check(ok: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), label))
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {label}" + (f"  ({detail})" if detail and not ok else ""), flush=True)
    return bool(ok)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def register(c: httpx.Client, tag: str) -> tuple[str, str]:
    """A throwaway account; returns (token, email)."""
    email = f"smoke-{tag}-{uuid.uuid4().hex[:8]}@example.com"
    password = "Str0ng!Passw0rd"
    c.post("/auth/register", json={"full_name": f"Smoke {tag}", "email": email,
                                   "password": password})
    r = c.post("/auth/login", json={"email": email, "password": password})
    return r.json()["access_token"], email


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    base = sys.argv[1].rstrip("/")
    restart_check = "--restart-check" in sys.argv
    c = httpx.Client(base_url=base, timeout=180.0, follow_redirects=True)

    print(f"\n=== target: {base} ===")

    print("\n--- service is up and secure ---")
    r = c.get("/health")
    check(r.status_code == 200, f"/health responds ({r.status_code})")
    check(base.startswith("https://"), "served over HTTPS")
    docs = c.get("/docs")
    check(docs.status_code in (200, 404), f"/docs reachable or disabled ({docs.status_code})")

    # A production build must not leak stack traces or config.
    bad = c.get("/session/does-not-exist")
    check(bad.status_code in (401, 403, 404, 422),
          f"unknown id gives a clean error ({bad.status_code})")
    check("Traceback" not in bad.text, "no traceback in the error body")

    if restart_check:
        return restart_verify(c)

    print("\n--- signup / login ---")
    token_a, email_a = register(c, "a")
    token_b, _ = register(c, "b")
    check(bool(token_a) and bool(token_b), "two accounts signed up and logged in")
    me = c.get("/auth/me", headers=auth(token_a))
    check(me.status_code == 200, f"authenticated /auth/me ({me.status_code})")
    check(c.get("/auth/me").status_code in (401, 403),
          "anonymous /auth/me is refused")

    print("\n--- session + primary form upload (OCR runs here) ---")
    session = c.post("/session", headers=auth(token_a)).json()["session"]["session_id"]
    check(bool(session), "session created")

    form = Path("../samples/forms/sbi.pdf")
    if not form.exists():
        check(False, "sbi.pdf fixture present", str(form))
        return report()
    up = c.post("/upload", headers=auth(token_a),
                files={"file": ("sbi.pdf", io.BytesIO(form.read_bytes()), "application/pdf")})
    check(up.status_code in (200, 201), f"primary form uploaded ({up.status_code})")
    document = up.json()["document"]["document_id"]

    proc = c.post("/intelligence/process", headers=auth(token_a),
                  json={"document_id": document, "session_id": session, "is_primary": True})
    check(proc.status_code == 200, f"OCR + classification + extraction ({proc.status_code})")
    if proc.status_code == 200:
        body = proc.json()
        check(str(body).find("sbi") != -1, "classified as the SBI form")

    print("\n--- stored bytes come back from object storage ---")
    view = c.get(f"/upload/{document}/file", headers=auth(token_a))
    check(view.status_code == 200, f"uploaded document downloads ({view.status_code})")
    check(view.content[:4] == b"%PDF", "the bytes are the real PDF")

    print("\n--- canonical profile + progress ---")
    prof = c.get(f"/intelligence/profile/{session}", headers=auth(token_a))
    check(prof.status_code == 200, f"canonical profile reads ({prof.status_code})")
    prog = c.get(f"/session/{session}/progress", headers=auth(token_a))
    check(prog.status_code == 200, f"progress reads ({prog.status_code})")
    if prog.status_code == 200:
        check(prog.json().get("required_fields", 0) > 0, "progress knows the active form")

    print("\n--- AI-guided completion answers a question ---")
    nq = c.get(f"/session/{session}/next", headers=auth(token_a))
    check(nq.status_code == 200, f"next question served ({nq.status_code})")

    print("\n--- Knowledge Chat: RAG cites, workflow reads session ---")
    kq = c.post("/knowledge/query", headers=auth(token_a),
                json={"question": "Is PAN required?"})
    check(kq.status_code == 200, f"a KYC question answers ({kq.status_code})")
    if kq.status_code == 200:
        check(len(kq.json().get("citations", [])) > 0, "the answer is cited")
    wq = c.post("/knowledge/query", headers=auth(token_a),
                json={"question": "What is my progress?", "session_id": session})
    if wq.status_code == 200:
        check(wq.json().get("generator") == "session-state",
              f"workflow question uses session state ({wq.json().get('generator')})")

    print("\n--- ownership: User B is refused everything of User A's ---")
    for label, method, url in (
        ("session", c.get, f"/session/{session}"),
        ("profile", c.get, f"/intelligence/profile/{session}"),
        ("document", c.get, f"/upload/{document}/file"),
    ):
        rb = method(url, headers=auth(token_b))
        check(rb.status_code in (403, 404), f"User B refused the {label} ({rb.status_code})")
        ra = method(url)
        check(ra.status_code in (401, 403, 404), f"anonymous refused the {label} ({ra.status_code})")
    check(c.get(f"/session/{session}", headers=auth(token_a)).status_code == 200,
          "User A still reads their own session")

    STATE.write_text(json.dumps({"base": base, "email_a": email_a,
                                 "session": session, "document": document}, indent=1))
    print(f"\n  state saved to {STATE} — rerun with --restart-check after a redeploy")
    return report()


def restart_verify(c: httpx.Client) -> int:
    """Prove a previous run's state survived a restart/redeploy."""
    print("\n--- persistence across restart ---")
    if not STATE.exists():
        check(False, "previous smoke state present", "run without --restart-check first")
        return report()
    st = json.loads(STATE.read_text())
    password = "Str0ng!Passw0rd"
    login = c.post("/auth/login", json={"email": st["email_a"], "password": password})
    check(login.status_code == 200, f"the account still exists after restart ({login.status_code})")
    if login.status_code != 200:
        return report()
    token = login.json()["access_token"]

    s = c.get(f"/session/{st['session']}", headers=auth(token))
    check(s.status_code == 200, f"the session survived ({s.status_code})")
    p = c.get(f"/intelligence/profile/{st['session']}", headers=auth(token))
    check(p.status_code == 200, f"the canonical profile survived ({p.status_code})")
    g = c.get(f"/session/{st['session']}/progress", headers=auth(token))
    check(g.status_code == 200, f"progress survived ({g.status_code})")
    if g.status_code == 200:
        check(g.json().get("required_fields", 0) > 0, "the active form survived")
    d = c.get(f"/upload/{st['document']}/file", headers=auth(token))
    check(d.status_code == 200, f"the uploaded document is still readable ({d.status_code})")
    check(d.content[:4] == b"%PDF", "its bytes came back from object storage intact")
    return report()


def report() -> int:
    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{'=' * 62}")
    print(f"LIVE SMOKE: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for label in failed:
        print(f"  FAILED: {label}")
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
