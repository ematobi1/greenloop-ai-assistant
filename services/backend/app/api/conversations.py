import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.conversation import ConversationManager
from app.ai.engine import AIEngine, Delta, Failed, Finished
from app.api.deps import get_request_id, get_session
from app.schemas import (
    ConversationCreate,
    ConversationList,
    ConversationOut,
    ListMeta,
    MessageCreate,
    MessageList,
    MessageOut,
    SendMessageResult,
)
from app.security.dependencies import get_principal, require_token

router = APIRouter(
    prefix="/v1/conversations", tags=["conversations"], dependencies=[Depends(require_token)]
)

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def manager_for(session: Session, principal: str) -> ConversationManager:
    return ConversationManager(session, principal)


@router.post("", status_code=201, response_model=ConversationOut)
def create_conversation(
    body: ConversationCreate,
    request: Request,
    session: Session = Depends(get_session),
    principal: str = Depends(get_principal),
):
    return manager_for(session, principal).create(
        body.title, body.instructions, get_request_id(request)
    )


@router.get("", response_model=ConversationList)
def list_conversations(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    principal: str = Depends(get_principal),
):
    rows, total = manager_for(session, principal).list_active(limit, offset)
    return ConversationList(data=rows, meta=ListMeta(total=total))


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: str,
    session: Session = Depends(get_session),
    principal: str = Depends(get_principal),
):
    return manager_for(session, principal).get(conversation_id)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    request: Request,
    session: Session = Depends(get_session),
    principal: str = Depends(get_principal),
) -> None:
    manager_for(session, principal).delete(conversation_id, get_request_id(request))


@router.get("/{conversation_id}/messages", response_model=MessageList)
def list_messages(
    conversation_id: str,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    principal: str = Depends(get_principal),
):
    rows, total = manager_for(session, principal).list_messages(conversation_id, limit, offset)
    return MessageList(data=rows, meta=ListMeta(total=total))


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: MessageCreate,
    request: Request,
    principal: str = Depends(get_principal),
):
    engine: AIEngine = request.app.state.ai_engine
    turn = engine.prepare(
        principal, conversation_id, body.content, body.provider, get_request_id(request)
    )
    if "text/event-stream" in request.headers.get("accept", ""):
        return StreamingResponse(
            event_stream(engine, turn), media_type="text/event-stream", headers=SSE_HEADERS
        )
    reply = await engine.run_to_completion(turn)
    return SendMessageResult(
        user_message=MessageOut.model_validate(turn.user_message),
        assistant_message=MessageOut.model_validate(reply),
    )


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def message_json(message) -> dict | None:
    return MessageOut.model_validate(message).model_dump(mode="json") if message else None


async def event_stream(engine: AIEngine, turn) -> AsyncIterator[str]:
    yield sse("message", {"user_message": message_json(turn.user_message)})
    events = engine.run(turn)
    try:
        async for event in events:
            if isinstance(event, Delta):
                yield sse("delta", {"text": event.text})
            elif isinstance(event, Finished):
                yield sse("done", {"assistant_message": message_json(event.message)})
            elif isinstance(event, Failed):
                yield sse(
                    "error",
                    {
                        "code": f"AI_{event.error.code.upper()}",
                        "message": event.error.public_message,
                        "partial_message": message_json(event.partial_message),
                    },
                )
    finally:
        await events.aclose()
