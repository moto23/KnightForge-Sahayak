"""
Asset continuation — a cached photo/signature must ANSWER its field.

The bug this pins: the stored image file and the interview answer are two
different things, and only the upload path ever wrote the answer. Every route
that cleared it (switching to a form with no photo box, deleting the primary
form) left the FILE behind and the answer gone. Re-activating a form that wants
a photograph then asked for one the session was already holding, so
"Keep & Continue" handed back the very same question, forever.

Usage:  python e2e_asset_continuation.py
"""

import asyncio
import io
import sys

import fitz
from fastapi import UploadFile

from app.core.dependencies import (
    asset_service,
    document_intelligence_service as dis,
    interview_service,
    session_service,
    upload_service,
)
from app.domain.form_assets import ASSET_FIELD_IDS, AssetKind

RESULTS: list[tuple[bool, str]] = []
PHOTO_FIELD = ASSET_FIELD_IDS[AssetKind.PHOTO]
SIGN_FIELD = ASSET_FIELD_IDS[AssetKind.SIGNATURE]


def check(ok: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


def store(raw: bytes, name: str):
    return asyncio.run(upload_service.store_upload(UploadFile(
        file=io.BytesIO(raw), filename=name,
        headers={"content-type": "application/pdf"})))


def png(w: int, h: int, rgb) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    page.draw_rect(fitz.Rect(0, 0, w, h), color=rgb, fill=rgb)
    raw = page.get_pixmap().tobytes("png")
    doc.close()
    return raw


def answers(sid: str) -> dict:
    return session_service.get_session(sid).answers


def supply_assets(sid: str) -> None:
    asset_service.store(sid, AssetKind.PHOTO, "photo.png", "image/png",
                        png(150, 190, (1, 0, 0)))
    asset_service.store(sid, AssetKind.SIGNATURE, "sign.png", "image/png",
                        png(240, 60, (0, 0.5, 0)))


def answer_everything_else(sid: str, limit: int = 60) -> list[str]:
    """Answer every non-asset question, so the assets are what remains."""
    filled = []
    for _ in range(limit):
        _, question = interview_service.next_question(sid)
        if question is None or question.field_type == "asset":
            break
        value = (question.options[0].value if question.options
                 else "18-07-2026" if "date" in question.id
                 else "7447524240" if question.id == "mobile"
                 else "raju@example.com" if question.id == "email"
                 else "CLDPP1659Q" if question.id == "pan"
                 else "844587274125" if question.id == "aadhaar"
                 else "261403" if question.id == "pincode"
                 else "TEST VALUE")
        interview_service.submit_answer(sid, question.id, value)
        filled.append(question.id)
    return filled


def main() -> int:
    raw = open("../samples/forms/icici.pdf", "rb").read()

    print("\n--- the reported loop: cached asset, cleared answer ---")
    sid = session_service.create_session().session_id
    doc = store(raw, "icici.pdf")
    dis.process_document(doc.document_id, sid, is_primary=True)
    supply_assets(sid)
    check(PHOTO_FIELD in answers(sid), "uploading answers the photo field")

    # Deleting the primary form retracts the answer; the FILE stays.
    upload_service.delete_document(doc.document_id)
    dis.get_profile(sid)
    check(PHOTO_FIELD not in answers(sid), "deleting the form retracts the answer")
    check(asset_service.get(sid, AssetKind.PHOTO) is not None,
          "the image file survives the form deletion")

    # Re-uploading the same form must re-adopt what the session already holds.
    doc2 = store(raw, "icici.pdf")
    dis.process_document(doc2.document_id, sid, is_primary=True)
    check(PHOTO_FIELD in answers(sid), "re-activating re-adopts the cached photo")
    check(SIGN_FIELD in answers(sid), "re-activating re-adopts the cached signature")

    print("\n--- the interview no longer asks for a satisfied asset ---")
    answer_everything_else(sid)
    _, question = interview_service.next_question(sid)
    check(question is None or question.field_type != "asset",
          f"no asset question remains ({question.id if question else 'complete'})",
          str(question.id if question else None))
    seen = []
    for _ in range(3):
        _, q = interview_service.next_question(sid)
        seen.append(q.id if q else None)
    check(len(set(seen)) == 1 and seen[0] is None,
          f"the interview is complete and stays complete ({seen})", str(seen))
    check(interview_service.current_progress(sid).progress_percentage == 100.0,
          "progress reaches 100%",
          str(interview_service.current_progress(sid).progress_percentage))

    print("\n--- adoption is idempotent ---")
    before = dict(answers(sid))
    for _ in range(3):
        dis.get_profile(sid)
        dis._adopt_available_assets(sid, dis.asset_requirements(sid))
    check(answers(sid) == before, "repeated adoption changes nothing")
    check(answers(sid)[PHOTO_FIELD] == before[PHOTO_FIELD],
          "the adopted asset id is stable")

    print("\n--- reload does not recreate the loop ---")
    for _ in range(3):
        dis.get_profile(sid)
        _, q = interview_service.next_question(sid)
        check(q is None, "still complete after a re-sync", str(q.id if q else None))

    print("\n--- Remove returns the field to pending, Replace re-answers ---")
    asset_service.delete(sid, AssetKind.PHOTO)
    check(PHOTO_FIELD not in answers(sid), "Remove clears the answer")
    check(asset_service.get(sid, AssetKind.PHOTO) is None, "Remove deletes the file")
    progress = interview_service.current_progress(sid).progress_percentage
    check(progress < 100.0, f"Remove drops progress below 100% ({progress})")
    _, q = interview_service.next_question(sid)
    check(q is not None and q.id == PHOTO_FIELD,
          "the interview asks for the photo again",
          str(q.id if q else None))

    asset_service.store(sid, AssetKind.PHOTO, "photo2.png", "image/png",
                        png(160, 200, (0, 0, 1)))
    check(PHOTO_FIELD in answers(sid), "Replace answers the field again")
    _, q = interview_service.next_question(sid)
    check(q is None, "the interview is complete again",
          str(q.id if q else None))
    check(interview_service.current_progress(sid).progress_percentage == 100.0,
          "progress returns to 100%")

    print("\n--- a form with NO photo box still retracts (regression) ---")
    sid2 = session_service.create_session().session_id
    doc3 = store(raw, "icici.pdf")
    dis.process_document(doc3.document_id, sid2, is_primary=True)
    supply_assets(sid2)
    check(PHOTO_FIELD in answers(sid2), "photo answered on the ICICI form")
    # Axis CK001 has no photo box: the answer must be retracted, NOT adopted.
    axis = store(open("../samples/forms/axis.pdf", "rb").read(), "axis.pdf")
    dis.process_document(axis.document_id, sid2, is_primary=True)
    check(PHOTO_FIELD not in answers(sid2),
          "switching to a form with no photo box retracts the photo answer")
    check(SIGN_FIELD in answers(sid2),
          "the signature it DOES require stays answered")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{'=' * 60}")
    print(f"ASSET CONTINUATION: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for label in failed:
        print(f"  FAILED: {label}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
