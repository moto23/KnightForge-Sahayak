"""
Knowledge Chat routing — the right source answers each kind of question.

Four sources, and the point is that they never swap places:

  * conversational / platform -> Sahayak's own voice
  * KYC knowledge            -> retrieval over the official corpus, cited
  * "what's left for ME?"     -> the session's authoritative state
  * date / time               -> the server clock

The bug: questions about the user's OWN form ("is my photo uploaded?") contain
domain words, so they were classified as KYC and sent to retrieval — which only
knows official documents and nothing about this applicant.

Usage:  python e2e_knowledge_chat.py
"""

import io
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.knowledge_intent import QueryIntent, classify_intent

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


client = TestClient(app)


def register(tag: str) -> str:
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    body = {"full_name": tag, "email": email, "password": "Str0ng!Passw0rd"}
    client.post("/auth/register", json=body)
    return client.post("/auth/login", json={
        "email": email, "password": body["password"]}).json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def ask(question: str, token: str | None = None, session_id: str | None = None):
    body: dict = {"question": question}
    if session_id:
        body["session_id"] = session_id
    return client.post("/knowledge/query", json=body,
                       headers=auth(token) if token else {})


def main() -> int:
    print("\n--- routing: each question reaches the right source ---")
    expected = {
        QueryIntent.CONVERSATIONAL: [
            "Hi", "How are you?", "Who are you?", "What can you do?",
            "How does Sahayak work?", "What is this app?",
        ],
        QueryIntent.WORKFLOW: [
            "What is my progress?", "What fields are missing?",
            "What should I answer next?", "What is remaining?",
            "Is my photo uploaded?", "Is my signature uploaded?",
            "Am I done?", "How far along am I?",
        ],
        QueryIntent.KYC: [
            "Is PAN required?", "What is KRA?",
            "Is Aadhaar mandatory for CVL KYC?",
            "Do I need a photo on the SBI form?",
            "What documents count as proof of address?",
        ],
        QueryIntent.DATETIME: ["today's date", "what is the time now"],
        QueryIntent.OUT_OF_DOMAIN: [
            "What is the capital of France?", "Who won the cricket match?",
        ],
    }
    for intent, questions in expected.items():
        for q in questions:
            got = classify_intent(q)
            check(got is intent, f"{q!r} -> {intent.value}", f"got {got.value}")

    print("\n--- conversational answers come from Sahayak, not retrieval ---")
    for q in ("Hi", "Who are you?", "What can you do?", "How does Sahayak work?"):
        r = ask(q)
        check(r.status_code == 200, f"{q!r} answers ({r.status_code})")
        body = r.json()
        check(body.get("generator") == "sahayak-assistant",
              f"{q!r} answered as Sahayak ({body.get('generator')})")
        check(not body.get("citations"), f"{q!r} cites no KYC document")
        check(len(body.get("answer", "")) > 10, f"{q!r} gives a real answer")

    print("\n--- date/time comes from the server clock ---")
    r = ask("today's date")
    check(r.json().get("generator") == "server-clock",
          f"date answered from the clock ({r.json().get('generator')})")

    print("\n--- unsupported questions are refused honestly ---")
    r = ask("What is the capital of France?")
    body = r.json()
    check(r.status_code == 200, "an off-topic question still answers 200")
    check(body.get("confident") is False, "it is marked not confident")
    check("paris" not in body.get("answer", "").lower(),
          f"it does not answer from general knowledge ({body.get('answer', '')[:60]!r})")

    print("\n--- workflow questions read the session, not the corpus ---")
    token = register("kc")
    session = client.post("/session", headers=auth(token)).json()["session"]["session_id"]
    sbi = Path("../samples/forms/sbi.pdf").read_bytes()
    doc = client.post("/upload", headers=auth(token),
                      files={"file": ("sbi.pdf", io.BytesIO(sbi), "application/pdf")}
                      ).json()["document"]["document_id"]
    client.post("/intelligence/process", headers=auth(token),
                json={"document_id": doc, "session_id": session, "is_primary": True})
    client.post(f"/session/{session}/answer", headers=auth(token),
                json={"field_id": "full_name", "value": "RAJUBHAI PATEL"})

    for q in ("What is my progress?", "What fields are missing?",
              "What should I answer next?", "Is my photo uploaded?"):
        r = ask(q, token, session)
        body = r.json()
        check(body.get("generator") == "session-state",
              f"{q!r} answered from session state ({body.get('generator')})")
        check(not body.get("citations"), f"{q!r} cites no KYC document")

    progress_answer = ask("What is my progress?", token, session).json()["answer"]
    check("%" in progress_answer, f"progress is quoted ({progress_answer[:60]!r})")
    check("1 of" in progress_answer, "the answered-field count is real")
    missing = ask("What fields are missing?", token, session).json()["answer"]
    check("Father" in missing or "Date of Birth" in missing,
          f"real pending fields are named ({missing[:80]!r})")
    photo = ask("Is my photo uploaded?", token, session).json()["answer"]
    check("photograph" in photo.lower(),
          f"the photograph is addressed ({photo[:80]!r})")
    check("still needed" in photo.lower(),
          "it correctly reports the photograph as missing")

    print("\n--- without a session it says so, and invents nothing ---")
    r = ask("What is my progress?")
    body = r.json()
    check(body.get("confident") is False, "no session -> not confident")
    check("%" not in body.get("answer", ""),
          f"no progress number is invented ({body.get('answer', '')[:60]!r})")

    print("\n--- another user's session is never read ---")
    other = register("other")
    r = ask("What is my progress?", other, session)
    body = r.json()
    check(body.get("confident") is False,
          "User B gets no state for User A's session")
    check("1 of" not in body.get("answer", ""),
          f"User A's progress does not leak ({body.get('answer', '')[:60]!r})")

    print("\n--- genuine KYC questions still reach retrieval ---")
    r = ask("Is PAN required?")
    check(r.status_code in (200, 409, 503),
          f"a KYC question reaches the RAG path ({r.status_code})")
    if r.status_code == 200:
        check(r.json().get("generator") not in ("session-state", "server-clock"),
              f"it is not answered from session state ({r.json().get('generator')})")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{'=' * 60}")
    print(f"KNOWLEDGE CHAT: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for label in failed:
        print(f"  FAILED: {label}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
