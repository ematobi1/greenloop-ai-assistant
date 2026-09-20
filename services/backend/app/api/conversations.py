from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_request_id, get_session
from app.errors import ApiError
from app.repositories import audit, conversations
from app.schemas import ConversationCreate, ConversationList, ConversationOut, ListMeta
from app.security.dependencies import require_token

router = APIRouter(
    prefix="/v1/conversations", tags=["conversations"], dependencies=[Depends(require_token)]
)


def get_or_404(session: Session, conversation_id: str):
    conversation = conversations.get_active(session, conversation_id)
    if conversation is None:
        raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation not found")
    return conversation


@router.post("", status_code=201, response_model=ConversationOut)
def create_conversation(
    body: ConversationCreate, request: Request, session: Session = Depends(get_session)
):
    conversation = conversations.create(session, body.title)
    audit.record(
        session, "conversation.create", "conversation", conversation.id, get_request_id(request)
    )
    session.commit()
    return conversation


@router.get("", response_model=ConversationList)
def list_conversations(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    rows, total = conversations.list_active(session, limit, offset)
    return ConversationList(data=rows, meta=ListMeta(total=total))


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, session: Session = Depends(get_session)):
    return get_or_404(session, conversation_id)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str, request: Request, session: Session = Depends(get_session)
) -> None:
    conversation = get_or_404(session, conversation_id)
    conversations.soft_delete(session, conversation)
    audit.record(
        session, "conversation.delete", "conversation", conversation.id, get_request_id(request)
    )
    session.commit()
