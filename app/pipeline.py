import os
import pandas as pd
from rdkit import Chem
from rdkit.Chem import Descriptors


class MoleculePipeline:
    def __init__(self, data_path: str = "data/compounds.csv"):
        self.data_path = data_path

    def run(self) -> dict:
        if not os.path.exists(self.data_path):
            return {"error": f"Data file not found: {self.data_path}"}

        df = pd.read_csv(self.data_path)
        required_cols = {"smiles", "compound_id", "target_protein"}
        if not required_cols.issubset(df.columns):
            return {"error": f"CSV missing columns. Expected: {required_cols}"}

        results = [self._analyse(row) for _, row in df.iterrows()]
        passed = sum(1 for r in results if r.get("lipinski_pass") is True)

        return {
            "total": len(results),
            "lipinski_pass": passed,
            "lipinski_fail": len(results) - passed,
            "compounds": results,
        }

    def _analyse(self, row) -> dict:
        mol = Chem.MolFromSmiles(row["smiles"])
        if mol is None:
            return {"compound_id": row["compound_id"], "smiles": row["smiles"], "error": "Could not parse SMILES."}

        mw = Descriptors.ExactMolWt(mol)
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
            "lipinski_pass": mw <= 500 and logp <= 5 and hbd <= 5 and hba <= 10,
        }
