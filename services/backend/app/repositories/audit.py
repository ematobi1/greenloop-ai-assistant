from sqlalchemy.orm import Session

from app.models import AuditEvent

LOCAL_ACTOR = "local-token"


def record(
    session: Session, action: str, resource_type: str, resource_id: str | None, request_id: str
) -> None:
    session.add(
        AuditEvent(
            actor=LOCAL_ACTOR,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
        )
    )
