import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from sqlmodel import Field, Index, SQLModel, Session, create_engine

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, echo=False)


class AuditLog(SQLModel, table=True):
    __table_args__ = (Index("ix_auditlog_researcher_id", "researcher_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    researcher_id: str
    target_gene: str
    active_smiles: str
    # queued → running → complete | error
    status: str = "queued"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
