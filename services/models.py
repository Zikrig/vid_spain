from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), default="Основная")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    pushes: Mapped[list["PushMessage"]] = relationship(back_populates="campaign")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(255), default="direct")
    subscribed_to_channel: Mapped[bool] = mapped_column(Boolean, default=False)
    got_lead_magnet: Mapped[bool] = mapped_column(Boolean, default=False)
    consultation_clicked: Mapped[bool] = mapped_column(Boolean, default=False)
    warmup_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    warmup_stopped: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PushMessage(Base):
    __tablename__ = "push_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    image_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    button_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    button_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    stop_on_consultation_click: Mapped[bool] = mapped_column(Boolean, default=True)

    campaign: Mapped["Campaign"] = relationship(back_populates="pushes")


class PushDelivery(Base):
    __tablename__ = "push_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    push_id: Mapped[int] = mapped_column(ForeignKey("push_messages.id"))
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    clicked: Mapped[bool] = mapped_column(Boolean, default=False)


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    invite_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BotContent(Base):
    __tablename__ = "bot_content"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    text: Mapped[str] = mapped_column(Text, default="")
    image_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
