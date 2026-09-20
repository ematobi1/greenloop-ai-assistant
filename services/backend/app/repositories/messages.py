from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Message


def next_sequence(session: Session, conversation_id: str) -> int:
    highest = session.scalar(
        select(func.max(Message.sequence)).where(Message.conversation_id == conversation_id)
    )
    return (highest or 0) + 1


def list_ordered(
    session: Session, conversation_id: str, limit: int, offset: int
) -> tuple[list[Message], int]:
    visible = (Message.conversation_id == conversation_id, Message.deleted_at.is_(None))
    total = session.scalar(select(func.count()).select_from(Message).where(*visible))
    rows = session.scalars(
        select(Message).where(*visible).order_by(Message.sequence).limit(limit).offset(offset)
    ).all()
    return list(rows), total or 0


def recent_history(session: Session, conversation_id: str, limit: int) -> list[Message]:
    newest_first = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.deleted_at.is_(None))
        .order_by(Message.sequence.desc())
        .limit(limit)
    ).all()
    return list(reversed(newest_first))
