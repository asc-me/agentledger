"""Public feedback attachments (bug screenshots). Stored in the DB, served
public-read by unguessable id. Validated: images only, size-capped."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Attachment

MAX_BYTES = 3 * 1024 * 1024  # 3 MB
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


class AttachmentError(ValueError):
    pass


def create_attachment(db: Session, *, content_type: str, data: bytes) -> Attachment:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct not in ALLOWED_TYPES:
        raise AttachmentError(f"unsupported type: {ct or 'unknown'} (images only)")
    if len(data) == 0:
        raise AttachmentError("empty file")
    if len(data) > MAX_BYTES:
        raise AttachmentError(f"file too large ({len(data)} bytes, max {MAX_BYTES})")
    att = Attachment(
        id="att_" + uuid.uuid4().hex[:14],
        content_type=ct,
        size=len(data),
        data=data,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


def get_attachment(db: Session, attachment_id: str) -> Attachment | None:
    return db.get(Attachment, attachment_id)


def valid_ids(db: Session, ids: list[str]) -> list[str]:
    """Keep only ids that resolve to a real attachment (cap the count)."""
    return [i for i in (ids or [])[:6] if db.get(Attachment, i) is not None]
