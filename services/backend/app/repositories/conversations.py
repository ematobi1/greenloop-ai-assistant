from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Conversation
from app.models.base import utc_now


def create(
    session: Session, owner: str, title: str, instructions: str | None = None
) -> Conversation:
    conversation = Conversation(owner=owner, title=title, instructions=instructions)
    session.add(conversation)
    session.flush()
    return conversation


def list_active(
    session: Session, owner: str, limit: int, offset: int
) -> tuple[list[Conversation], int]:
    visible = (Conversation.owner == owner, Conversation.deleted_at.is_(None))
    total = session.scalar(select(func.count()).select_from(Conversation).where(*visible))
    rows = session.scalars(
        select(Conversation)
        .where(*visible)
        .order_by(Conversation.created_at.desc(), Conversation.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total or 0


def get_active(session: Session, owner: str, conversation_id: str) -> Conversation | None:
    return session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.owner == owner,
            Conversation.deleted_at.is_(None),
        )
    )


def soft_delete(session: Session, conversation: Conversation) -> None:
    conversation.deleted_at = utc_now()
