from fastapi import FastAPI, Depends
from pydantic import BaseModel

from app.auth import login, get_current_user
from app.database import engine, init_db, AuditLog, Session
from app.worker import run_mmff94_minimisation
from app.pipeline import MoleculePipeline

app = FastAPI(
    title="Molecule Recovery Agent",
    description="3D conformer generation and Lipinski screening for failed formulations.",
    version="1.0.0",
)


@app.on_event("startup")
def on_startup():
    init_db()


app.post("/token")(login)


class RecoveryRequest(BaseModel):
    target_gene: str
    active_smiles: str
    failed_excipient_smiles: str


@app.post("/api/v1/recover")
def recover_formulation(
    payload: RecoveryRequest,
    researcher_id: str = Depends(get_current_user),
):
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

    task = run_mmff94_minimisation.delay(payload.active_smiles)

    try:
        result = task.get(timeout=20)
    except Exception:
        result = {"error": "Worker timed out. Check Celery is running."}

    with Session(engine) as session:
        log_entry = session.get(AuditLog, log.id)
        if log_entry:
            log_entry.status = "error" if "error" in result else "complete"
            session.add(log_entry)
            session.commit()

    return {
        "audit_log_id": log.id,
        "researcher_id": researcher_id,
        "target_gene": payload.target_gene,
        "minimisation": result,
    }


@app.get("/api/v1/screen")
def screen_compounds(researcher_id: str = Depends(get_current_user)):
    return MoleculePipeline().run()


@app.get("/health")
def health():
    return {"status": "ok"}
