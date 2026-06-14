from celery import Celery
from rdkit import Chem
from rdkit.Chem import AllChem

# 1. CPU DECOUPLING: Route heavy tasks to Redis message broker
celery_app = Celery("chemistry_tasks", broker="redis://localhost:6379/0", backend="redis://localhost:6379/0")

@celery_app.task
def compute_mmff94_forcefield(smiles: str):
    """Executes heavy 3D minimization off the main API thread."""
    mol = Chem.MolFromSmiles(smiles)
    if not mol:
        return {"error": "Invalid SMILES structure"}
    
    mol_3d = Chem.AddHs(mol)
    try:
        AllChem.EmbedMolecule(mol_3d, randomSeed=1337, maxAttempts=40)
        ff = AllChem.MMFFGetMoleculeForceField(mol_3d, AllChem.MMFFGetMoleculeProperties(mol_3d))
        ff.Initialize()
        ff.Minimize()
        strain = round(ff.CalcEnergy(), 2)
        
        conformer = mol_3d.GetConformer()
        spatial_points = [
            {'element': atom.GetSymbol(), 
             'x': round(conformer.GetAtomPosition(i).x, 3), 
             'y': round(conformer.GetAtomPosition(i).y, 3), 
             'z': round(conformer.GetAtomPosition(i).z, 3)} 
            for i, atom in enumerate(mol.GetAtoms())
        ]
        
        return {"strain_energy_kcal_mol": strain, "atomic_point_cloud": spatial_points}
    except Exception as e:
        return {"error": str(e), "strain_energy_kcal_mol": 99.9}
