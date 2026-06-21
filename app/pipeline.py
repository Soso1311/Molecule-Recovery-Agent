"""
Attempted to implement the Lipinski Rule-of-Five screening pipeline. Within this, the compound CSV is loaded once at module import and cached and subsequent
calls to MoleculePipeline().run() pay no disk I/O.
"""

import os
from functools import lru_cache
from pathlib import Path

import pandas as pd
from rdkit import Chem
from rdkit.Chem import Descriptors

# Resolve path relative to this file so it works regardless of cwd
_DEFAULT_CSV = Path(__file__).parent.parent / "data" / "compounds.csv"


@lru_cache(maxsize=1)
def _load_dataframe(data_path: str) -> pd.DataFrame:
    return pd.read_csv(data_path)


def _analyse_row(row: pd.Series) -> dict:
    mol = Chem.MolFromSmiles(row["smiles"])
    if mol is None:
        return {
            "compound_id": row["compound_id"],
            "smiles": row["smiles"],
            "error": "Could not parse SMILES.",
        }

    # Lipinski's Rule of Five Pipeline will implement the average molecular weight (MolWt),
    # but it may also use the monoisotopic exact mass (ExactMolWt). Not too sure tho lwk.
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
        # Lipinski uses ≤ not <; all four criteria must pass
        "lipinski_pass": mw <= 500 and logp <= 5 and hbd <= 5 and hba <= 10,
    }


class MoleculePipeline:
    def __init__(self, data_path: str | None = None) -> None:
        self.data_path = str(data_path or _DEFAULT_CSV)

    def run(self) -> dict:
        if not os.path.exists(self.data_path):
            return {"error": f"Data file not found: {self.data_path}"}

        df = _load_dataframe(self.data_path)

        required_cols = {"smiles", "compound_id", "target_protein"}
        missing = required_cols - set(df.columns)
        if missing:
            return {"error": f"CSV missing columns: {missing}"}

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
