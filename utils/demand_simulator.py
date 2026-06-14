"""
demand_simulator.py
Simuliert Bestelldaten nach Poisson-Verteilung mit trendabhängiger Anpassung.
Basierend auf VBA-Logik, aber mit Python-optimierungen.
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple
from pathlib import Path


# Produktkonfiguration mit Mittelwerten pro Tag (Fallbacks)
HARD_CODED_DEFAULTS = {
    'CT5': {'lambda': 16.28, 'std': 1.43},
    'CT6': {'lambda': 3.08, 'std': 0.25},
    'CT7': {'lambda': 4.32, 'std': 1.46},
    'TT6': {'lambda': 14.04, 'std': 2.97},
    'TT7': {'lambda': 5.18, 'std': 1.17},
    'TT8': {'lambda': 0.87, 'std': 0.16}
}
COLORS = {
    'CT5': '#1f77b4',  # blau
    'CT6': '#ff7f0e',  # orange
    'CT7': '#2ca02c',  # grün
    'TT6': '#d62728',  # rot
    'TT7': '#9467bd',  # violett
    'TT8': '#8c564b'   # braun
}


def _load_default_products_from_csv(defaults: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """Generate DEFAULT_PRODUCTS from data/raw/Demand_Simulation.csv."""
    csv_path = Path(__file__).parent.parent / 'data' / 'raw' / 'Demand_Simulation.csv'
    if not csv_path.exists():
        return {p: dict(cfg) for p, cfg in defaults.items()}
    try:
        try:
            df = pd.read_csv(csv_path, encoding='utf-8-sig')
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, encoding='cp1252')

        def _to_float(v, default: float) -> float:
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return float(default)
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v).strip()
            if not s:
                return float(default)
            s = s.replace(',', '.')
            try:
                return float(s)
            except Exception:
                return float(default)

        mean_col_candidates = (
            'Durchschnittliche_Nachfrage_taeglich',
            'Durchschnittliche_Nachfrage_täglich',
        )
        std_col_candidates = (
            'Standardabweichung_Tagesnachfrage',
            'Variabilitaet_Standardabweichung',
        )
        mean_col = next((c for c in mean_col_candidates if c in df.columns), None)
        std_col = next((c for c in std_col_candidates if c in df.columns), None)

        products: Dict[str, Dict[str, float]] = {}
        for _, row in df.iterrows():
            name = str(row.get('Produkt', '')).strip()
            if not name:
                continue
            base = defaults.get(name, {})
            products[name] = {
                'lambda': _to_float(row.get(mean_col) if mean_col else None, float(base.get('lambda', 0.0))),
                'std': _to_float(row.get(std_col) if std_col else None, float(base.get('std', 0.0))),
            }
        return products or {p: dict(cfg) for p, cfg in defaults.items()}
    except Exception:
        return {p: dict(cfg) for p, cfg in defaults.items()}


DEFAULT_PRODUCTS = _load_default_products_from_csv(HARD_CODED_DEFAULTS)


def _load_case_study_products(defaults: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """Load lambda/std per product from data/raw/Demand_Simulation.csv."""
    csv_path = Path(__file__).parent.parent / 'data' / 'raw' / 'Demand_Simulation.csv'
    products = {p: dict(cfg) for p, cfg in defaults.items()}
    if not csv_path.exists():
        return products
    try:
        try:
            df = pd.read_csv(csv_path, encoding='utf-8-sig')
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, encoding='cp1252')

        def _to_float(v, default: float) -> float:
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return float(default)
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v).strip()
            if not s:
                return float(default)
            s = s.replace(',', '.')
            try:
                return float(s)
            except Exception:
                return float(default)

        mean_col_candidates = (
            'Durchschnittliche_Nachfrage_taeglich',
            'Durchschnittliche_Nachfrage_täglich',
        )
        std_col_candidates = (
            'Standardabweichung_Tagesnachfrage',
            'Variabilitaet_Standardabweichung',
        )
        mean_col = next((c for c in mean_col_candidates if c in df.columns), None)
        std_col = next((c for c in std_col_candidates if c in df.columns), None)

        for _, row in df.iterrows():
            name = str(row.get('Produkt', '')).strip()
            if name not in products:
                continue
            base = products[name]
            products[name] = {
                'lambda': _to_float(row.get(mean_col) if mean_col else None, float(base.get('lambda', 0.0))),
                'std': _to_float(row.get(std_col) if std_col else None, float(base.get('std', 0.0))),
            }
        return products
    except Exception:
        return products


PRODUCTS = _load_case_study_products(DEFAULT_PRODUCTS)
PRODUCT_NAMES = list(PRODUCTS.keys())


def poisson_generator(lambda_param: float) -> int:
    """Generiert eine Poisson-verteilte Zufallszahl (Knuth-Algorithmus).
    
    Parameters
    ----------
    lambda_param : float
        Mittelwert (lambda) der Poisson-Verteilung
        
    Returns
    -------
    int
        Poisson-verteilte Zufallszahl
    """
    if lambda_param <= 0:
        return 0
    
    L = np.exp(-lambda_param)
    k = 0
    p = 1.0
    
    while p > L:
        k += 1
        p *= np.random.uniform(0, 1)
    
    return k - 1


def _load_case_study_daily_means() -> Dict[str, float]:
    """Load mean daily demand per product from Demand_Simulation.csv (via PRODUCTS)."""
    return {p: float(cfg.get('lambda', 0.0) or 0.0) for p, cfg in PRODUCTS.items()}


def run_simulation(num_days: int, trend: float) -> Tuple[pd.DataFrame, Dict]:
    """Führt die Bestellsimulation durch.
    
    Parameters
    ----------
    num_days : int
        Anzahl der Simulationstage
    trend : float
        Trendwert (-10 bis +10, normiert)
        Negative Werte = Abnehmender Trend
        Positive Werte = Zunehmender Trend
        
    Returns
    -------
    Tuple[pd.DataFrame, Dict]
        - DataFrame mit simulierten Tageswerten
        - Dict mit Summen und ADU pro Produkt
    """
    
    # Normalisiere Trend (von -10...10 zu Exponentialfaktor)
    # trend_factor: -10 -> 0.1x (90% Reduktion), 0 -> 1.0x, +10 -> 10x
    trend_factor = 10 ** (trend / 10.0)  # Exponential-Skalierung
    
    # Basis-Lambdas aus Case Study CSV (vereinheitlicht mit globaler Nachfragequelle)
    base_lambdas = _load_case_study_daily_means()

    # Initialisiere Datenstrukturen
    data = {'Day': list(range(1, num_days + 1))}
    prev_values = {product: float(base_lambdas.get(product, PRODUCTS[product]['lambda'])) for product in PRODUCT_NAMES}

    # Simuliere für jeden Tag
    for day in range(1, num_days + 1):
        for product in PRODUCT_NAMES:
            # Basis-Lambda mit Trend anpassen
            base_lambda = float(base_lambdas.get(product, PRODUCTS[product]['lambda']))
            
            # Exponentieller Trend über die Tage
            lambda_t = base_lambda * (trend_factor ** ((day - 1) / num_days))
            
            # Mindestgrenze (20% der Basis-Lambda)
            lambda_t = max(lambda_t, base_lambda * 0.2)
            
            # Poisson-Stichprobe
            value = poisson_generator(lambda_t)

            # Glättung auf dem gezogenen Wert (VBA-Logik)
            if day > 1:
                value = 0.7 * prev_values[product] + 0.3 * value
            prev_values[product] = value
            
            # Speichere in DataFrame
            if product not in data:
                data[product] = []
            rounded_value = int(round(value))
            data[product].append(rounded_value)
    
    df = pd.DataFrame(data)
    
    # Berechne Summen und ADU pro Produkt
    summary = {}
    for product in PRODUCT_NAMES:
        total = df[product].sum()
        adu = total / num_days  # Average Daily Usage
        summary[product] = {
            'Summe': total,
            'ADU': round(adu, 2)
        }
    
    return df, summary


def get_product_colors() -> Dict[str, str]:
    """Gibt die Farbzuordnung pro Produkt zurück."""
    return COLORS


def get_product_names() -> list:
    """Gibt die Liste der Produktnamen zurück."""
    return PRODUCT_NAMES
