from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Conversation
from app.models.base import utc_now


def create(session: Session, title: str) -> Conversation:
    conversation = Conversation(title=title)
    session.add(conversation)
    session.flush()
    return conversation


def list_active(session: Session, limit: int, offset: int) -> tuple[list[Conversation], int]:
    active = Conversation.deleted_at.is_(None)
    total = session.scalar(select(func.count()).select_from(Conversation).where(active))
    rows = session.scalars(
        select(Conversation)
        .where(active)
        .order_by(Conversation.created_at.desc(), Conversation.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total or 0


def get_active(session: Session, conversation_id: str) -> Conversation | None:
    return session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.deleted_at.is_(None)
        )
    )


def soft_delete(session: Session, conversation: Conversation) -> None:
    conversation.deleted_at = utc_now()
