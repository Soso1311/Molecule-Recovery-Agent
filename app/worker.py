import os
from celery import Celery
from rdkit import Chem
from rdkit.Chem import AllChem
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("chemistry_tasks", broker=REDIS_URL, backend=REDIS_URL)


@celery_app.task
def run_mmff94_minimisation(smiles: str) -> dict:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"error": "Could not parse SMILES string."}

    mol_3d = Chem.AddHs(mol)
    if AllChem.EmbedMolecule(mol_3d, randomSeed=42, maxAttempts=50) != 0:
        return {"error": "3D embedding failed."}

    props = AllChem.MMFFGetMoleculeProperties(mol_3d)
    if props is None:
        return {"error": "MMFF94 properties unavailable for this molecule."}

    ff = AllChem.MMFFGetMoleculeForceField(mol_3d, props)
    ff.Initialize()
    ff.Minimize()

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

    return {"strain_energy_kcal_mol": round(ff.CalcEnergy(), 4), "atoms": coords}
