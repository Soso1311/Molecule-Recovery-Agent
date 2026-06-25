"""
Database configuration and the models

Schema notes

AuditLog.status will be constrained to the four valid state values via a Python Enum. The SQLModel maps this to a VARCHAR with a CHECK 
constraint. The celery_task_id is stored on the log so GET /tasks/{id} results can be correlated back to audit records without keeping
it only in memory. The Indexes are declared on researcher_id and status, which are the two columns most likely to appear in WHERE 
clauses.

Migration

The SQLModel's create_all() is fine for initial schema creation but cannot handle schema changes at all(adding/removing columns). Once
the project is at a stage where we are consdiering the schema to evolve, we will migrate Alembic:

    pip install alembic
    alembic init alembic
    # point alembic/env.py at SQLModel.metadata and DATABASE_URL
    alembic revision --autogenerate -m "initial"
    alembic upgrade head
    
"""

import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from dotenv import load_dotenv
from sqlmodel import Field, Index, SQLModel, create_engine

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, echo=False)


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    complete = "complete"
    error = "error"


class AuditLog(SQLModel, table=True):
    __table_args__ = (
        # researcher_id and status are the two most common filter columns
        Index("ix_auditlog_researcher_id", "researcher_id"),
        Index("ix_auditlog_status", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    researcher_id: str
    target_gene: str
    active_smiles: str
    # Celery task ID stored so the record can be linked to async results.
    celery_task_id: Optional[str] = Field(default=None)
    status: TaskStatus = TaskStatus.queued
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
