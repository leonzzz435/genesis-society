"""Short serialized world transactions. No database lock spans model/network I/O."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class World(Base):
    __tablename__ = "society_world"
    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class Request(Base):
    __tablename__ = "society_request"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    actor: Mapped[str] = mapped_column(String, index=True)
    phase: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSON)


class Store:
    def __init__(self, url: str):
        self.engine = create_engine(url, pool_pre_ping=True)

    @contextmanager
    def transaction(self):
        with Session(self.engine) as session, session.begin():
            row = session.scalar(select(World).where(World.id == 1).with_for_update())
            if row is None:
                raise ValueError("Run society init-demo first; initialization is never automatic")
            state = deepcopy(row.data)
            yield session, state
            row.data = state

    def snapshot(self):
        with Session(self.engine) as session:
            row = session.get(World, 1)
            if row is None:
                raise ValueError("World not initialized")
            return deepcopy(row.data)

    def requests(self):
        with Session(self.engine) as session:
            return [
                dict(id=r.id, actor=r.actor, phase=r.phase, **deepcopy(r.data))
                for r in session.scalars(select(Request).order_by(Request.created_at))
            ]

    def requests_summary(self):
        with Session(self.engine) as session:
            return [
                dict(
                    id=r.id,
                    actor=r.actor,
                    phase=r.phase,
                    purpose=(r.data or {}).get("purpose", "decision"),
                    profile=(r.data or {}).get("profile"),
                    usage=(r.data or {}).get("usage"),
                    world_clock=(r.data or {}).get("world_clock"),
                )
                for r in session.scalars(select(Request).order_by(Request.created_at))
            ]

    def trace_ids(self, actor, limit=4, exclude_prefix=""):
        with Session(self.engine) as session:
            stmt = select(Request.id).where(Request.actor == actor)
            if exclude_prefix:
                stmt = stmt.where(~Request.id.startswith(exclude_prefix))
            return list(
                reversed(
                    list(session.scalars(stmt.order_by(Request.created_at.desc()).limit(limit)))
                )
            )

    @contextmanager
    def owner(self):
        # A dedicated session-level lock also excludes a second CLI/worker process.
        with self.engine.connect() as connection:
            if not connection.scalar(text("SELECT pg_try_advisory_lock(77401231)")):
                raise RuntimeError("Another society owner is running")
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(77401231)"))


def uid():
    return str(uuid4())


def utcnow():
    return datetime.now(UTC)
