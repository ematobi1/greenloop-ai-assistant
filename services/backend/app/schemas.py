from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, PlainSerializer, StringConstraints


def format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


Timestamp = Annotated[datetime, PlainSerializer(format_timestamp, return_type=str)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ActionName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ListMeta(BaseModel):
    total: int


class ConversationCreate(BaseModel):
    title: Title


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
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
