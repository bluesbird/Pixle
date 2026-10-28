import os
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON, CheckConstraint, Date, DateTime, ForeignKey, Integer, String,
    UniqueConstraint, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Person(Base):
    __tablename__ = "people"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list[str]] = mapped_column(JSON)


class Puzzle(Base):
    __tablename__ = "puzzles"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[str] = mapped_column(ForeignKey("people.id"))
    levels: Mapped[list[dict]] = mapped_column(JSON)


class Player(Base):
    __tablename__ = "players"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        UniqueConstraint("player_id", "puzzle_date"),
        CheckConstraint("attempts >= 0"),
        CheckConstraint("status IN ('playing', 'won', 'lost')"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.token_hash"), index=True)
    puzzle_date: Mapped[date] = mapped_column(ForeignKey("puzzles.date"))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="playing")


class Guess(Base):
    __tablename__ = "guesses"
    __table_args__ = (
        UniqueConstraint("game_id", "request_id"),
        UniqueConstraint("game_id", "person_id"),
        UniqueConstraint("game_id", "attempt"),
        CheckConstraint("attempt > 0"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(36))
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id"))
    attempt: Mapped[int] = mapped_column(Integer)


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (CheckConstraint("score >= 0"),)

    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), primary_key=True)
    score: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


def make_engine(url=None):
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is required (postgresql+psycopg://user:password@host/pixle)")
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    if engine.dialect.name not in ("postgresql", "sqlite"):
        engine.dispose()
        raise ValueError("Only PostgreSQL and explicit SQLite development/test databases are supported")
    if engine.dialect.name == "sqlite":
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine
