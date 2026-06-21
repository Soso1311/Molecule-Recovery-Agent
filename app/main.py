"""
Molecule Recovery Agent — FastAPI application.
"""

from contextlib import asynccontextmanager

import celery.exceptions
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.auth import _load_users, login, get_current_user
from app.database import engine, init_db, AuditLog
from app.pipeline import MoleculePipeline
from app.worker import celery_app, run_mmff94_minimisation


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    _load_users()
    init_db()
    yield


app = FastAPI(
    title="Molecule Recovery Agent",
    description="3D conformer generation and Lipinski screening for failed formulations.",
    version="1.1.0",
    lifespan=lifespan,
)

app.post("/token")(login)


# ── Request / Response models ──────────────────────────────────────────────────

class RecoveryRequest(BaseModel):
    target_gene: str
    active_smiles: str
    failed_excipient_smiles: list[str] = []  # wired through to response for future processing


class TaskStatus(BaseModel):
    task_id: str
    status: str
    result: dict | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/api/v1/recover")
def recover_formulation(
    payload: RecoveryRequest,
    researcher_id: str = Depends(get_current_user),
) -> dict:
    """
    Submits an MMFF94 minimisation task and returns a task_id immediately.
    Poll GET /api/v1/tasks/{task_id} for the result.
    """
    with Session(engine) as session:
        log = AuditLog(
            researcher_id=researcher_id,
            target_gene=payload.target_gene,
            active_smiles=payload.active_smiles,
            status="queued",
        )
        session.add(log)
        session.commit()
        session.refresh(log)
        audit_log_id = log.id

    task = run_mmff94_minimisation.delay(payload.active_smiles)

    # Store the task_id in the audit log so we can look it up later
    with Session(engine) as session:
        log_entry = session.get(AuditLog, audit_log_id)
        if log_entry:
            log_entry.status = "running"
            session.add(log_entry)
            session.commit()

    return {
        "audit_log_id": audit_log_id,
        "task_id": task.id,
        "researcher_id": researcher_id,
        "target_gene": payload.target_gene,
        "failed_excipient_smiles": payload.failed_excipient_smiles,
        "message": "Task submitted. Poll /api/v1/tasks/{task_id} for the result.",
    }


@app.get("/api/v1/tasks/{task_id}", response_model=TaskStatus)
def get_task_status(
    task_id: str,
    _: str = Depends(get_current_user),
) -> TaskStatus:
    """
    Returns the current state of a minimisation task.
    status values: PENDING | STARTED | SUCCESS | FAILURE
    """
    result = celery_app.AsyncResult(task_id)
    return TaskStatus(
        task_id=task_id,
        status=result.status,
        result=result.result if result.ready() else None,
    )


@app.get("/api/v1/screen")
def screen_compounds(researcher_id: str = Depends(get_current_user)) -> dict:
    """Runs Lipinski Rule-of-Five screening against the compound library."""
    return MoleculePipeline().run()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
