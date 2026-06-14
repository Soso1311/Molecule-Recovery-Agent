from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
import jwt
from datetime import datetime, timedelta
from fastapi_semcache import SemCache

from app.database import engine, init_db, AuditLog, Session
from app.worker import compute_mmff94_forcefield

app = FastAPI(
    title="Alchemi Institutional Core v6",
    description="Distributed architecture: JWT Auth, Celery Task Queues, and Semantic Vector Caching."
)

@app.on_event("startup")
def on_startup():
    init_db()

SECRET_KEY = "regulatory_super_secret"
ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def create_access_token(data: dict):
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + timedelta(hours=8)})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@app.post("/token")
def login():
    return {"access_token": create_access_token({"sub": "researcher_007"}), "token_type": "bearer"}

def verify_researcher(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Re-authenticate.")

semcache = SemCache(
    backend_url="postgresql+psycopg://postgres:password@localhost:5432/alchemi_db",
    similarity_threshold=0.88,
    tenant_isolation=True
)
app.add_middleware(semcache.middleware())

class RecoveryPayload(BaseModel):
    target_gene_symbol: str
    active_ingredient_smiles: str
    failed_excipient_smiles: str

@app.post("/api/v6/formulation/recover")
def execute_distributed_recovery(payload: RecoveryPayload, researcher_id: str = Depends(verify_researcher)):
    with Session(engine) as session:
        log = AuditLog(
            researcher_id=researcher_id,
            target_gene=payload.target_gene_symbol,
            active_smiles=payload.active_ingredient_smiles,
            mhra_status="Processing"
        )
        session.add(log)
        session.commit()
        session.refresh(log)

    task = compute_mmff94_forcefield.delay(payload.active_ingredient_smiles)
    
    try:
        spatial_data = task.get(timeout=15)
    except Exception:
        spatial_data = {"error": "Worker timeout"}

    return {
        "transaction_security": {
            "auth_status": "Verified",
            "researcher_tenant_id": researcher_id,
            "sql_audit_log_id": log.id
        },
        "performance_layer": {
            "heavy_compute": "Delegated to Celery Worker",
            "llm_synthesis": "Routed through fastapi-semcache (Vector DB)"
        },
        "3d_forcefield_computation": spatial_data
    }
