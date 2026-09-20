from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import AuditEvent, Conversation, Message
from app.models.base import new_id, utc_now
from app.repositories import audit, conversations, messages

MAX_SEQUENCE_ATTEMPTS = 5


class ConversationManager:
    """Owner-scoped access to conversations and their messages.

    Every lookup filters by owner, and a conversation owned by someone else is
    reported as not found so its existence is not revealed.
    """

    def __init__(self, session: Session, owner: str):
        self._session = session
        self._owner = owner

    def create(self, title: str, instructions: str | None, request_id: str) -> Conversation:
        conversation = conversations.create(self._session, self._owner, title, instructions)
        audit.record(
            self._session, "conversation.create", "conversation", conversation.id, request_id
        )
        self._session.commit()
        return conversation

    def list_active(self, limit: int, offset: int) -> tuple[list[Conversation], int]:
        return conversations.list_active(self._session, self._owner, limit, offset)

    def get(self, conversation_id: str) -> Conversation:
        conversation = conversations.get_active(self._session, self._owner, conversation_id)
        if conversation is None:
            raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation not found")
        return conversation

    def delete(self, conversation_id: str, request_id: str) -> None:
        conversation = self.get(conversation_id)
        conversations.soft_delete(self._session, conversation)
        audit.record(
            self._session, "conversation.delete", "conversation", conversation.id, request_id
        )
        self._session.commit()

    def list_messages(
        self, conversation_id: str, limit: int, offset: int
    ) -> tuple[list[Message], int]:
        conversation = self.get(conversation_id)
        return messages.list_ordered(self._session, conversation.id, limit, offset)

    def history(self, conversation_id: str, limit: int) -> list[Message]:
        conversation = self.get(conversation_id)
        return messages.recent_history(self._session, conversation.id, limit)

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        request_id: str,
        status: str = "complete",
        provider: str | None = None,
        model: str | None = None,
    ) -> Message:
        """Store a message with the next sequence number and commit.

        Two writers can compute the same sequence. The unique constraint rejects the
        loser, which rolls back and retries with a fresh number.
        """
        for _ in range(MAX_SEQUENCE_ATTEMPTS):
            conversation = self.get(conversation_id)
            message = Message(
                id=new_id(),
                conversation_id=conversation.id,
                sequence=messages.next_sequence(self._session, conversation.id),
                role=role,
                content=content,
                status=status,
                provider=provider,
                model=model,
            )
            self._session.add(message)
            self._session.add(
                AuditEvent(
                    actor=audit.LOCAL_ACTOR,
                    action=f"message.{role}",
                    resource_type="message",
                    resource_id=message.id,
                    request_id=request_id,
                )
            )
            conversation.updated_at = utc_now()
            if provider and not conversation.provider:
                conversation.provider, conversation.model = provider, model
            try:
                self._session.commit()
            except IntegrityError:
                self._session.rollback()
                continue
            return message
        raise ApiError(409, "MESSAGE_SEQUENCE_CONFLICT", "Could not order the message, try again")
