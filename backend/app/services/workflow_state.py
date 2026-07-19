"""
Plain-language description of ONE session's current state.

Knowledge Chat needs to answer "what's left?", "what should I answer next?" and
"is my photo uploaded?". Those look like KYC questions — they contain words like
"photo" and "PAN" — but retrieval can only answer from official documents and
knows nothing about this applicant. Letting the model answer them instead would
mean inventing someone's KYC progress.

So the answer is COMPOSED from the authoritative state the rest of the product
already computes: the session's own progress, its remaining required fields, and
its asset requirements. Nothing here re-derives or re-implements any of that —
it only reads and phrases it, so Knowledge Chat can never disagree with the
Progress page.
"""

from app.domain.form_assets import ASSET_FIELD_IDS
from app.services.form_service import form_service
from app.services.interview_service import InterviewService
from app.services.session_service import SessionService

# How many pending fields to name before summarising the rest.
_NAMED_LIMIT = 8


def describe_session_state(
    session_id: str,
    sessions: SessionService,
    interview: InterviewService,
) -> str | None:
    """One paragraph of fact about this session, or None when unreadable."""
    try:
        session = sessions.get_session(session_id)
        progress = interview.current_progress(session_id)
    except Exception:  # noqa: BLE001 - Knowledge Chat must not 500 over this
        return None

    parts: list[str] = []

    # The form is deliberately NOT named. `session.form_id` is the base
    # registry form, not the ACTIVE primary schema, so quoting it would tell an
    # SBI applicant they are filling a CVL form. The Upload and Progress pages
    # already show which form is active; stating it wrongly here is worse than
    # leaving it to them.
    if session.required_field_ids is not None and not session.required_field_ids:
        return (
            "There is no active KYC form on this session yet, so there is "
            "nothing to complete. Upload or choose your primary form on the "
            "Upload page and I will track it from there."
        )

    parts.append(
        f"Your form is {progress.progress_percentage:.0f}% complete — "
        f"{progress.completed_required_fields} of "
        f"{progress.required_fields} required fields are done."
    )

    by_id = {f.id: f for f in form_service.get_all_fields()}
    names = [
        by_id[fid].display_name if fid in by_id else fid
        for fid in progress.pending_required_fields
    ]
    if names:
        shown = ", ".join(names[:_NAMED_LIMIT])
        more = len(names) - _NAMED_LIMIT
        parts.append(
            f"Still to answer: {shown}"
            + (f", and {more} more." if more > 0 else ".")
        )
        parts.append(f"The next question is {names[0]}.")
    else:
        parts.append("Every required field is answered — your form is ready to generate.")

    # Photograph / signature, only when the ACTIVE form actually asks for them.
    scope = session.required_field_ids
    for field_id in ASSET_FIELD_IDS.values():
        if scope is not None and field_id not in scope:
            continue
        label = "photograph" if "photo" in field_id else "signature"
        supplied = field_id in session.answers
        parts.append(
            f"Your {label} has been uploaded."
            if supplied
            else f"Your {label} is still needed."
        )

    if session.skipped_fields:
        parts.append(
            f"You chose to skip {len(session.skipped_fields)} optional "
            "question(s); you can still fill them in at any time."
        )

    return " ".join(parts)
