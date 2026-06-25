"""
Lipinski Rule-of-Five screening pipeline.

Design decisions

The compound CSV is going to be loaded once at module import and cached via lru_cache. The Subsequent calls to 
MoleculePipeline().run() incur no disk I/O. The Row processing uses df.apply() rather than df.iterrows(), this is because the other is 
a Python-level loop that negates pandas entirely as apply() keeps processing in the C layer and is materially faster on large 
DataFrames. I also introduced a hard row cap (MAX_ROWS) prevents a runaway CSV from OOM-ing the API. MolWt (average molecular weight)
is used, but now not the ExactMolWt (monoisotopic). Lipinski's original paper specifies average MW through using the monoisotopic mass
gives incorrect pass/fail classifications at the 500 Da boundary. The column is named target_protein in the CSV. The API field 
returned in the JSON response is also target_protein so the naming is consistent end-to-end. (A previous version of main.py used 
target_gene which refers to the molecule being targeted, stored separately in RecoveryRequest.)
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

import pandas as pd
from rdkit import Chem
from rdkit.Chem import Descriptors

logger = logging.getLogger(__name__)

# Resolves the relative to this file so it works regardless of the working directory.
_DEFAULT_CSV = Path(__file__).parent.parent / "data" / "compounds.csv"

# Hard cap: refuse to process more than this many rows in a single call.
# Callers needing larger screens should paginate or run offline.
MAX_ROWS = 10_000


@lru_cache(maxsize=1)
def _load_dataframe(data_path: str) -> pd.DataFrame:
    """Load the compound CSV and cache it for the lifetime of the process."""
    df = pd.read_csv(data_path, nrows=MAX_ROWS)
    logger.info("Loaded %d compounds from %s.", len(df), data_path)
    return df


def _analyse_row(row: pd.Series) -> dict:
    """Compute Lipinski descriptors for a single compound row."""
    mol = Chem.MolFromSmiles(row["smiles"])
    if mol is None:
        return {
            "compound_id": row["compound_id"],
            "smiles": row["smiles"],
            "error": "Could not parse SMILES.",
        }

    # MolWt = average molecular weight which is correct for Lipinski Ro5.
    # ExactMolWt = monoisotopic mass as it is NOT what Lipinski specifies.
    mw = Descriptors.MolWt(mol)
    logp = Descriptors.MolLogP(mol)
    hbd = Descriptors.NumHDonors(mol)
    hba = Descriptors.NumHAcceptors(mol)

    return {
        "compound_id": row["compound_id"],
        "target_protein": row["target_protein"],
        "smiles": row["smiles"],
        "molecular_weight": round(mw, 3),
        "logp": round(logp, 3),
        "h_bond_donors": hbd,
        "h_bond_acceptors": hba,
        # Lipinski uses ≤ (not <) for all four criteria.
        "lipinski_pass": mw <= 500 and logp <= 5 and hbd <= 5 and hba <= 10,
    }


class MoleculePipeline:
    def __init__(self, data_path: str | None = None) -> None:
        self.data_path = str(data_path or _DEFAULT_CSV)

    def run(self) -> dict:
        """
        Load the compound library and run Ro5 screening.

        Returns a summary dict on success.
        Returns {"error": "..."} on failure — callers (main.py) must convert
        this to an HTTPException with an appropriate status code.
        """
        if not os.path.exists(self.data_path):
            return {"error": f"Data file not found: {self.data_path}"}

        try:
            df = _load_dataframe(self.data_path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load compound CSV: %s", exc)
            return {"error": f"Could not read compound CSV: {exc}"}

        required_cols = {"smiles", "compound_id", "target_protein"}
        missing = required_cols - set(df.columns)
        if missing:
            return {"error": f"CSV missing required columns: {sorted(missing)}"}

        # df.apply() keeps processing in pandas/C making it much faster than iterrows().
        results = df.apply(_analyse_row, axis=1).tolist()

        parse_errors = [r for r in results if "error" in r]
        passed = [r for r in results if r.get("lipinski_pass") is True]
        failed = [r for r in results if r.get("lipinski_pass") is False]

        return {
            "total": len(results),
            "parse_errors": len(parse_errors),
            "lipinski_pass": len(passed),
            "lipinski_fail": len(failed),
            "compounds": results,
        }
