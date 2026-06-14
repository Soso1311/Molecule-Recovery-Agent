from sqlmodel import SQLModel, Field, create_engine, Session
from datetime import datetime
from typing import Optional

DATABASE_URL = "postgresql+psycopg://postgres:password@localhost:5432/alchemi_db"
engine = create_engine(DATABASE_URL, echo=False)

class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    researcher_id: str
    target_gene: str
    active_smiles: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    mhra_status: str

def init_db():
    SQLModel.metadata.create_all(engine)
