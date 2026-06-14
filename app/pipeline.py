import pandas as pd
from rdkit import Chem
from rdkit.Chem import Descriptors
import os

class PharmaPipeline:
    def __init__(self, data_path: str = 'data/compounds.csv'):
        self.data_path = data_path

    def load_and_analyze(self):
        if not os.path.exists(self.data_path):
            return {'error': f'Data file not found at {self.data_path}'}
        
        df = pd.read_csv(self.data_path)
        results = []

        for _, row in df.iterrows():
            smiles = row['smiles']
            mol = Chem.MolFromSmiles(smiles)
            
            if mol:
                mw = Descriptors.ExactMolWt(mol)
                logp = Descriptors.MolLogP(mol)
                hbd = Descriptors.NumHDonors(mol)
                hba = Descriptors.NumHAcceptors(mol)
                
                lipinski_passed = (mw <= 500) and (logp <= 5) and (hbd <= 5) and (hba <= 10)
                
                results.append({
                    'compound_id': row['compound_id'],
                    'target_protein': row['target_protein'],
                    'smiles': smiles,
                    'molecular_weight': round(mw, 2),
                    'logp': round(logp, 2),
                    'lipinski_compliant': bool(lipinski_passed)
                })
            else:
                results.append({
                    'compound_id': row['compound_id'],
                    'error': 'Invalid SMILES string parsed'
                })
                
        return {'processed_count': len(results), 'compounds': results}
