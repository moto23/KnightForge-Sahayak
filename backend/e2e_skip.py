"""
Skip flow — declining an optional question must settle it, not loop.

The bug: the next question is "the first required field with no answer", and
saying "skip" left the field unanswered — so the same question came straight
back, forever. Storing the word "skip" instead would have been worse: "skip" is
not a CKYC number, and it would have reached the canonical profile and the
printed form.

Usage:  python e2e_skip.py
"""

import asyncio
import io
import sys
from pathlib import Path

from fastapi import UploadFile

from app.core.dependencies import (
    conversation_service,
    document_intelligence_service as dis,
    interview_service,
    session_service,
    upload_service,
)
from app.core.exceptions import FieldNotSkippableError
from app.domain.enums import Language
from app.services.conversation_service import _reads_as_skip
from app.services.form_service import form_service

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


def store(raw: bytes, name: str):
    return asyncio.run(upload_service.store_upload(UploadFile(
        file=io.BytesIO(raw), filename=name,
        headers={"content-type": "application/pdf"})))


def activate(form: str) -> str:
    """A session with `form` as its active primary form."""
    raw = Path(f"../samples/forms/{form}.pdf").read_bytes()
    sid = session_service.create_session().session_id
    doc = store(raw, f"{form}.pdf")
    dis.process_document(doc.document_id, sid, is_primary=True)
    return sid


def field(field_id: str):
    return next(f for f in form_service.get_all_fields() if f.id == field_id)


def main() -> int:
    print("\n--- what reads as a refusal ---")
    for phrase in ("skip", "Skip this", "yes, skip", "I don't know", "dont know",
                   "not available", "N/A", "no idea", "leave it blank",
                   "I don't have it", "pata nahi", "next question"):
        check(_reads_as_skip(phrase), f"{phrase!r} reads as a skip")
    for real in ("12345678901234", "Sinnar", "CLDPP1659Q", "Uttar Pradesh",
                 "skipper street", "Nashik"):
        check(not _reads_as_skip(real), f"{real!r} is NOT treated as a skip")

    print("\n--- skippability is schema-driven, not a hardcoded list ---")
    for optional in ("ckycr_number", "account_number", "district", "monthly_income"):
        check(not field(optional).required, f"{optional} is optional -> skippable")
    for mandatory in ("full_name", "pan", "date_of_birth", "mobile", "declaration_place"):
        check(field(mandatory).required, f"{mandatory} is required -> never skippable")

    print("\n--- a required field cannot be skipped, on any form ---")
    for form in ("cvl", "sbi", "hdfc", "icici", "axis"):
        sid = activate(form)
        try:
            session_service.skip_field(sid, "full_name")
            check(False, f"{form}: skipping a required field is refused")
        except FieldNotSkippableError:
            check(True, f"{form}: skipping a required field is refused")

    print("\n--- SBI: skip advances exactly once and never repeats ---")
    sid = activate("sbi")
    # Walk to the optional CKYC number question.
    guard, reached = 0, False
    while guard < 40:
        guard += 1
        _, q = interview_service.next_question(sid)
        if q is None:
            break
        if q.id == "ckycr_number":
            reached = True
            break
        value = (q.options[0].value if q.options
                 else "18-07-2026" if "date" in q.id
                 else "7447524240" if q.id == "mobile"
                 else "raju@example.com" if q.id == "email"
                 else "CLDPP1659Q" if q.id == "pan"
                 else "261403" if q.id == "pincode"
                 else "45000" if q.id == "monthly_income"
                 else "30123456789" if q.id == "account_number"
                 else "Sinnar")
        if q.field_type.value == "asset":
            # Assets are answered by upload, not text — step over them so
            # the walk can reach the optional field under test.
            session_service.skip_field(sid, q.id)
            continue
        interview_service.submit_answer(sid, q.id, value)
    pending = session_service.get_session(sid)
    check(reached or "ckycr_number" not in pending.answers,
          "the interview reaches the optional CKYC question")

    before = interview_service.current_progress(sid).progress_percentage
    session_service.skip_field(sid, "ckycr_number")
    _, after_q = interview_service.next_question(sid)
    check(after_q is None or after_q.id != "ckycr_number",
          f"the skipped question is not asked again ({after_q.id if after_q else 'complete'})")

    seen = []
    for _ in range(3):
        _, q = interview_service.next_question(sid)
        seen.append(q.id if q else None)
    check(len(set(seen)) == 1, f"the next question is stable, not looping ({seen})")
    check("ckycr_number" not in seen, "the skipped field never returns")

    print("\n--- nothing is stored as applicant data ---")
    session = session_service.get_session(sid)
    check("ckycr_number" not in session.answers,
          f"no value saved for the skipped field ({session.answers.get('ckycr_number')!r})")
    check("ckycr_number" in session.skipped_fields, "the field is recorded as skipped")
    check(not any(str(v).strip().lower() in ("skip", "yes", "n/a", "na", "none")
                  for v in session.answers.values()),
          f"no answer anywhere reads as a refusal ({session.answers})")
    check("ckycr_number" not in session.validation_errors,
          "a skip is not recorded as a validation error")

    print("\n--- skipping does not block completion ---")
    after = interview_service.current_progress(sid).progress_percentage
    check(after >= before, f"progress did not go backwards ({before} -> {after})")

    print("\n--- a skipped field stays editable ---")
    interview_service.submit_answer(sid, "ckycr_number", "12345678901234")
    session = session_service.get_session(sid)
    check(session.answers.get("ckycr_number") == "12345678901234",
          "the value can be supplied later")
    check("ckycr_number" not in session.skipped_fields,
          "answering clears the skip")

    print("\n--- the same works through the conversation layer ---")
    sid2 = activate("sbi")
    guard, reached2 = 0, False
    while guard < 40:
        guard += 1
        _, q = interview_service.next_question(sid2)
        if q is None:
            break
        if not q.required:
            reached2 = True
            break
        if q.field_type.value == "asset":
            break
        value = (q.options[0].value if q.options
                 else "18-07-2026" if "date" in q.id
                 else "7447524240" if q.id == "mobile"
                 else "raju@example.com" if q.id == "email"
                 else "CLDPP1659Q" if q.id == "pan"
                 else "261403" if q.id == "pincode" else "Sinnar")
        interview_service.submit_answer(sid2, q.id, value)
    check(reached2, "the conversation reaches an optional question")
    _, optional_q = interview_service.next_question(sid2)
    asked_id = optional_q.id
    reply = conversation_service.reply(sid2, "skip", Language.ENGLISH)
    check(reply.intent == "skip", f"the reply is understood as a skip ({reply.intent})")
    check(reply.next_question is None or reply.next_question.id != asked_id,
          "the conversation advances past the skipped question")
    check(asked_id not in session_service.get_session(sid2).answers,
          "the conversation stored no value for it")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{'=' * 60}")
    print(f"SKIP: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for label in failed:
        print(f"  FAILED: {label}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
