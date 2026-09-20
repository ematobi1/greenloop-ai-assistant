from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, UtcDateTime
from app.security.principal import LOCAL_PRINCIPAL


class Conversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    owner: Mapped[str] = mapped_column(String(50), default=LOCAL_PRINCIPAL, index=True)
    title: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
