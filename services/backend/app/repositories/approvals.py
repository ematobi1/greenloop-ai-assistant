from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Approval
from app.models.base import utc_now


def create(session: Session, action: str, description: str) -> Approval:
    approval = Approval(action=action, description=description, status="pending")
    session.add(approval)
    session.flush()
    return approval


def list_by_status(
    session: Session, status: str | None, limit: int, offset: int
) -> tuple[list[Approval], int]:
    filters = [Approval.status == status] if status else []
    total = session.scalar(select(func.count()).select_from(Approval).where(*filters))
    rows = session.scalars(
        select(Approval)
        .where(*filters)
        .order_by(Approval.created_at.desc(), Approval.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total or 0


def get(session: Session, approval_id: str) -> Approval | None:
    return session.get(Approval, approval_id, populate_existing=True)


def decide_if_pending(session: Session, approval_id: str, decision: str) -> bool:
    now = utc_now()
    result = session.execute(
        update(Approval)
        .where(Approval.id == approval_id, Approval.status == "pending")
        .values(status=decision, decided_at=now, updated_at=now)
    )
    return result.rowcount == 1
