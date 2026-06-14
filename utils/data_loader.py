"""
data_loader.py
Hilfsfunktionen zum Laden der Excel-Dateien.
"""

import pandas as pd
from pathlib import Path


def load_excel(path, sheet_name=0):
    """Lädt eine Excel-Datei als pandas.DataFrame.

    Parameters
    ----------
    path : str | Path
        Pfad zur Excel-Datei
    sheet_name : int | str
        Blattname oder Index

    Returns
    -------
    pd.DataFrame
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {path}")
    return pd.read_excel(path, sheet_name=sheet_name)
