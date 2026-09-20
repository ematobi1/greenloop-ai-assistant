from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, PlainSerializer, StringConstraints, field_validator


def format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


Timestamp = Annotated[datetime, PlainSerializer(format_timestamp, return_type=str)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ActionName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ListMeta(BaseModel):
    total: int


Instructions = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
MessageContent = Annotated[str, StringConstraints(min_length=1, max_length=100000)]


class ConversationCreate(BaseModel):
    title: Title
    instructions: Instructions | None = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    instructions: str | None
    provider: str | None
    model: str | None
    created_at: Timestamp
    updated_at: Timestamp


class ConversationList(BaseModel):
    data: list[ConversationOut]
    meta: ListMeta


class ApprovalCreate(BaseModel):
    action: ActionName
    description: Annotated[str, StringConstraints(max_length=500)] = ""


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "denied"]


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action: str
    description: str
    status: Literal["pending", "approved", "denied"]
    decided_at: Timestamp | None
    created_at: Timestamp
    updated_at: Timestamp


class ApprovalList(BaseModel):
    data: list[ApprovalOut]
    meta: ListMeta


class MessageCreate(BaseModel):
    content: MessageContent
    provider: Annotated[str, StringConstraints(max_length=50)] | None = None

    @field_validator("content")
    @classmethod
    def content_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    sequence: int
    role: Literal["user", "assistant", "system"]
    content: str
    status: Literal["complete", "incomplete", "failed"]
    provider: str | None
    model: str | None
    created_at: Timestamp


class MessageList(BaseModel):
    data: list[MessageOut]
    meta: ListMeta


class SendMessageResult(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut


class ProviderOut(BaseModel):
    name: str
    location: Literal["local", "cloud"]
    model: str
    available: bool
    detail: str
    default: bool


class ProviderList(BaseModel):
    data: list[ProviderOut]
    meta: ListMeta


class ModelOut(BaseModel):
    provider: str
    model: str
    default: bool


class ModelList(BaseModel):
    data: list[ModelOut]
    meta: ListMeta
