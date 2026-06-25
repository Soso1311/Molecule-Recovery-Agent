"""
The Celery worker aka the MMFF94 3D conformer generation and energy minimisation

New Safety controls Introduced to the system - 

SMILES length will be capped at MAX_SMILES_LEN before touching RDKit. A non fixed length or complex SMILES can consume an 
unbounded amount of CPU inside the C library with no Python-level timeout possible. This also tasks the soft/hard time limits guard 
against runaway minimisations. soft_time_limit raises SoftTimeLimitExceeded inside the task so it can clean up and the time_limit sends
SIGKILL if it doesn't exit in time. max_retries=3 with autoretry_for covers transient infrastructure failures (broker blip, OOM kill).
Deterministic failures (bad SMILES, embedding fail) are not retried but instead they return an error dict immediately. ff.Initialize() 
removed

MMFFGetMoleculeForceField() already initialises the force field object. Calling Initialize() again is a documented no-op and was removed
to avoid further confusion.
"""

import logging
import os

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded
from dotenv import load_dotenv
from rdkit import Chem
from rdkit.Chem import AllChem

load_dotenv()
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Maximum SMILES string length accepted by the worker.
# Beyond this, parsing time is unpredictable and embedding rarely succeeds.
MAX_SMILES_LEN = 1_000

celery_app = Celery("chemistry_tasks", broker=REDIS_URL, backend=REDIS_URL)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,          # Re-queue on worker crash before ack.
    worker_prefetch_multiplier=1, # Don't hoard tasks; allow fair distribution.
)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    # Soft limit: raises SoftTimeLimitExceeded inside the task after 120 s.
    # Hard limit: SIGKILL after 150 s if the task ignores the soft signal.
    soft_time_limit=120,
    time_limit=150,
    autoretry_for=(OSError, MemoryError),  # Transient infra errors only.
    retry_backoff=True,
)
def run_mmff94_minimisation(self, smiles: str) -> dict:
    """
    Generate a 3D conformer for *smiles* and minimise it with MMFF94.

    Returns a dict with 'strain_energy_kcal_mol' and per-atom coordinates
    on success, or {'error': '...'} on deterministic failure.

    Transient failures (OOM, broker blip) are retried up to max_retries times.
    """
    try:
        # ── Input validation ─────────────────────────────────────────────────
        if not smiles or not isinstance(smiles, str):
            return {"error": "SMILES must be a non-empty string."}

        if len(smiles) > MAX_SMILES_LEN:
            return {
                "error": (
                    f"SMILES length {len(smiles)} exceeds maximum of "
                    f"{MAX_SMILES_LEN} characters."
                )
            }

        # ── Parse ─────────────────────────────────────────────────────────────
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return {"error": "Could not parse SMILES string."}

        # ── 3D embedding ──────────────────────────────────────────────────────
        mol_3d = Chem.AddHs(mol)
        embed_result = AllChem.EmbedMolecule(mol_3d, randomSeed=42, maxAttempts=50)
        if embed_result != 0:
            return {"error": "3D embedding failed — molecule may be too complex or invalid."}

        # ── MMFF94 minimisation ───────────────────────────────────────────────
        # MMFFGetMoleculeForceField() initialises the force field internally.
        # A separate ff.Initialize() call is a documented no-op and was removed.
        props = AllChem.MMFFGetMoleculeProperties(mol_3d)
        if props is None:
            return {"error": "MMFF94 properties unavailable for this molecule."}

        ff = AllChem.MMFFGetMoleculeForceField(mol_3d, props)
        if ff is None:
            return {"error": "Could not construct MMFF94 force field."}

        ff.Minimize()

        # ── Extract coordinates ───────────────────────────────────────────────
        conformer = mol_3d.GetConformer()
        coords = [
            {
                "atom_index": i,
                "element": atom.GetSymbol(),
                "x": round(conformer.GetAtomPosition(i).x, 4),
                "y": round(conformer.GetAtomPosition(i).y, 4),
                "z": round(conformer.GetAtomPosition(i).z, 4),
            }
            for i, atom in enumerate(mol_3d.GetAtoms())
        ]

        return {
            "strain_energy_kcal_mol": round(ff.CalcEnergy(), 4),
            "atoms": coords,
        }

    except SoftTimeLimitExceeded:
        logger.error("MMFF94 minimisation timed out for SMILES: %.80s", smiles)
        return {"error": "Minimisation timed out — molecule may be too large or complex."}

    except MemoryError as exc:
        logger.exception("OOM during minimisation")
        raise self.retry(exc=exc)
