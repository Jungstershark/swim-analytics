"""
SQLAlchemy ORM models.

Models: Swimmer, Meet, Result, RelayResult, RelayLeg
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Swimmer(Base):
    __tablename__ = "Swimmer"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team: Mapped[str | None] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    results: Mapped[list["Result"]] = relationship(back_populates="swimmer", cascade="all, delete-orphan")

    __table_args__ = (
        Index("Swimmer_name_idx", "name"),
        Index("Swimmer_team_idx", "team"),
    )

    def __repr__(self) -> str:
        return f"<Swimmer(id={self.id}, name='{self.name}', team='{self.team}')>"


class Meet(Base):
    __tablename__ = "Meet"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    startDate: Mapped[datetime] = mapped_column("date", DateTime(timezone=True), nullable=False)
    endDate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    parserFormat: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "hytek"
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    results: Mapped[list["Result"]] = relationship(back_populates="meet", cascade="all, delete-orphan")

    __table_args__ = (
        Index("Meet_date_idx", "date"),
    )

    def __repr__(self) -> str:
        return f"<Meet(id={self.id}, name='{self.name}', startDate={self.startDate})>"


class Result(Base):
    __tablename__ = "Result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    swimmerId: Mapped[int] = mapped_column(Integer, ForeignKey("Swimmer.id"), nullable=False)
    meetId: Mapped[int] = mapped_column(Integer, ForeignKey("Meet.id"), nullable=False)
    event: Mapped[str] = mapped_column(String, nullable=False)
    time: Mapped[str | None] = mapped_column(String, nullable=True)
    seedTime: Mapped[str | None] = mapped_column(String, nullable=True)
    placement: Mapped[int | None] = mapped_column(Integer, nullable=True)
    isDQ: Mapped[bool] = mapped_column(Boolean, default=False)
    dqCode: Mapped[str | None] = mapped_column(String, nullable=True)
    dqDescription: Mapped[str | None] = mapped_column(String, nullable=True)
    isGuest: Mapped[bool] = mapped_column(Boolean, default=False)
    qualifier: Mapped[str | None] = mapped_column(String, nullable=True)
    reactionTime: Mapped[str | None] = mapped_column(String, nullable=True)
    splits: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON string of split data
    round: Mapped[str | None] = mapped_column(String, nullable=True)  # "Prelim", "Final", "Timed Final", "Semifinal"
    swimDate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # Actual date of this swim
    contentHash: Mapped[str | None] = mapped_column(String, nullable=True)  # SHA-256 for deduplication
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    swimmer: Mapped["Swimmer"] = relationship(back_populates="results")
    meet: Mapped["Meet"] = relationship(back_populates="results")

    __table_args__ = (
        Index("Result_swimmerId_idx", "swimmerId"),
        Index("Result_meetId_idx", "meetId"),
        Index("Result_event_idx", "event"),
        Index("Result_contentHash_idx", "contentHash"),
        Index("Result_dedup_idx", "swimmerId", "meetId", "event", "round", "swimDate"),
    )

    def __repr__(self) -> str:
        return f"<Result(id={self.id}, event='{self.event}', time='{self.time}')>"


class RelayResult(Base):
    __tablename__ = "RelayResult"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meetId: Mapped[int] = mapped_column(Integer, ForeignKey("Meet.id"), nullable=False)
    event: Mapped[str] = mapped_column(String, nullable=False)
    teamName: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "Olympians Swimming (Can)"
    relayLetter: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "A", "B"
    time: Mapped[str | None] = mapped_column(String, nullable=True)
    seedTime: Mapped[str | None] = mapped_column(String, nullable=True)
    placement: Mapped[int | None] = mapped_column(Integer, nullable=True)
    isDQ: Mapped[bool] = mapped_column(Boolean, default=False)
    dqCode: Mapped[str | None] = mapped_column(String, nullable=True)
    dqDescription: Mapped[str | None] = mapped_column(String, nullable=True)
    isExhibition: Mapped[bool] = mapped_column(Boolean, default=False)
    round: Mapped[str | None] = mapped_column(String, nullable=True)
    swimDate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    splits: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON string
    reactionTime: Mapped[str | None] = mapped_column(String, nullable=True)
    contentHash: Mapped[str | None] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    meet: Mapped["Meet"] = relationship()
    legs: Mapped[list["RelayLeg"]] = relationship(back_populates="relay_result", cascade="all, delete-orphan")

    __table_args__ = (
        Index("RelayResult_meetId_idx", "meetId"),
        Index("RelayResult_event_idx", "event"),
        Index("RelayResult_contentHash_idx", "contentHash"),
    )

    def __repr__(self) -> str:
        return f"<RelayResult(id={self.id}, event='{self.event}', team='{self.teamName}')>"


class RelayLeg(Base):
    __tablename__ = "RelayLeg"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    relayResultId: Mapped[int] = mapped_column(Integer, ForeignKey("RelayResult.id"), nullable=False)
    legNumber: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-4
    swimmerId: Mapped[int | None] = mapped_column(Integer, ForeignKey("Swimmer.id"), nullable=True)
    swimmerName: Mapped[str] = mapped_column(String, nullable=False)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String, nullable=True)  # "M" or "W" (from mixed relays)
    isGuest: Mapped[bool] = mapped_column(Boolean, default=False)
    reactionTime: Mapped[str | None] = mapped_column(String, nullable=True)  # Exchange RT
    splitTime: Mapped[str | None] = mapped_column(String, nullable=True)  # Their leg time

    relay_result: Mapped["RelayResult"] = relationship(back_populates="legs")
    swimmer: Mapped["Swimmer"] = relationship()

    __table_args__ = (
        Index("RelayLeg_relayResultId_idx", "relayResultId"),
        Index("RelayLeg_swimmerId_idx", "swimmerId"),
    )
