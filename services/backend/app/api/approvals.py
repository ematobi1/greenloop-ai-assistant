from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_request_id, get_session
from app.errors import ApiError
from app.repositories import approvals, audit
from app.schemas import ApprovalCreate, ApprovalDecision, ApprovalList, ApprovalOut, ListMeta
from app.security.dependencies import require_token

router = APIRouter(
    prefix="/v1/approvals", tags=["approvals"], dependencies=[Depends(require_token)]
)


def get_or_404(session: Session, approval_id: str):
    approval = approvals.get(session, approval_id)
    if approval is None:
        raise ApiError(404, "APPROVAL_NOT_FOUND", "Approval not found")
    return approval


@router.post("", status_code=201, response_model=ApprovalOut)
def create_approval(
    body: ApprovalCreate, request: Request, session: Session = Depends(get_session)
):
    approval = approvals.create(session, body.action, body.description)
    audit.record(session, "approval.create", "approval", approval.id, get_request_id(request))
    session.commit()
    return approval


@router.get("", response_model=ApprovalList)
def list_approvals(
    status: Literal["pending", "approved", "denied"] | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    rows, total = approvals.list_by_status(session, status, limit, offset)
    return ApprovalList(data=rows, meta=ListMeta(total=total))


@router.get("/{approval_id}", response_model=ApprovalOut)
def get_approval(approval_id: str, session: Session = Depends(get_session)):
    return get_or_404(session, approval_id)


@router.post("/{approval_id}/decision", response_model=ApprovalOut)
def decide_approval(
    approval_id: str,
    body: ApprovalDecision,
    request: Request,
    session: Session = Depends(get_session),
):
    if not approvals.decide_if_pending(session, approval_id, body.decision):
        session.rollback()
        get_or_404(session, approval_id)
        raise ApiError(409, "APPROVAL_ALREADY_DECIDED", "Approval was already decided")
    audit.record(
        session, f"approval.{body.decision}", "approval", approval_id, get_request_id(request)
    )
    session.commit()
    return get_or_404(session, approval_id)
