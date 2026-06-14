"""
utils/overflow_simulator.py

Overflow-Board Simulator für Kanban-Verwaltung nach DDMRP/Heijunka-Logik.
Folgt der Simulation aus Heijunka-Slides S. 5-7.

Funktionalität:
1. Bestelldaten tägliche Kanban-Verbräuche
2. Kanban-Einteilung in Zonen (Grün/Gelb/Rot)
3. Priorisierungslogik basierend auf Füllgrad
4. Pitch-Planung für Produktion
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import uuid

# ============================================================================
# Enums & Data Models
# ============================================================================

class Zone(Enum):
    """Kanban-Zonen im Overflow-Board"""
    GREEN = "green"    # Cycle Stock - normal (Green Zone)
    YELLOW = "yellow"  # Cycle Stock - erhöht (Yellow Zone)
    RED = "red"        # Safety Stock (Red Zone)


@dataclass
class ProductBuffer:
    """Pufferzonen-Konfiguration für ein Produkt"""
    name: str
    green_capacity: int      # Green Zone Slots
    yellow_capacity: int     # Yellow Zone Slots
    red_capacity: int        # Red Zone Slots
    total_kanbans: int       # Gesamt Kanbans im Umlauf (=Cycle Stock + Safety Stock)
    is_event_kanban: bool = False
    daily_usage: float = 0.0  # Average Daily Usage
    
    def get_max_kanbans(self) -> int:
        """Maximale Anzahl Kanbans"""
        return self.green_capacity + self.yellow_capacity + self.red_capacity


@dataclass
class OverflowBoard:
    """Overflow-Board State für alle Produkte"""
    products: Dict[str, ProductBuffer]
    current_kanbans: Dict[str, List[Zone]] = field(default_factory=dict)
    production_history: Dict[str, List[int]] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize current_kanbans und production_history"""
        for product_name in self.products:
            self.current_kanbans[product_name] = []
            self.production_history[product_name] = []
    
    def add_kanban(self, product_name: str, count: int = 1):
        """
        Füge Kanbans hinzu (z.B. weil Teile verbraucht wurden).
        Füllt automatisch von unten nach oben: Grün → Gelb → Rot
        """
        if product_name not in self.products:
            return
        
        buffer = self.products[product_name]
        
        for _ in range(count):
            # Zähle aktuelle Slots pro Zone
            green_count = sum(1 for z in self.current_kanbans[product_name] if z == Zone.GREEN)
            yellow_count = sum(1 for z in self.current_kanbans[product_name] if z == Zone.YELLOW)
            red_count = sum(1 for z in self.current_kanbans[product_name] if z == Zone.RED)

            # Platziere in nächstem Level (von unten: Grün → Gelb → Rot)
            if green_count < buffer.green_capacity:
                self.current_kanbans[product_name].append(Zone.GREEN)
            elif yellow_count < buffer.yellow_capacity:
                self.current_kanbans[product_name].append(Zone.YELLOW)
            elif red_count < buffer.red_capacity:
                self.current_kanbans[product_name].append(Zone.RED)
            # Wenn voll: ignoriere (Board ist voll - Notfall!)
    
    def remove_kanban(self, product_name: str, count: int = 1):
        """
        Entferne Kanbans (weil produziert wurde).
        Entfernt von oben nach unten: Rot → Gelb → Grün
        """
        if product_name not in self.products:
            return
        
        for _ in range(min(count, len(self.current_kanbans[product_name]))):
            # Entferne von oben (höchste Priority = Rot)
            if self.current_kanbans[product_name]:
                self.current_kanbans[product_name].pop()
    
    def get_fill_level(self, product_name: str) -> Tuple[float, Zone]:
        """
        Berechne Füllgrad eines Produkts.

        Rückgabe: (fill_percentage, current_max_zone)

        Priorisierung nach Folie:
        - Höchste Zone bestimmt Priorität (Rot > Gelb > Grün)
        - Innerhalb Zone: höherer Füllgrad = höhere Priorität
        """
        if product_name not in self.products:
            return (0.0, Zone.GREEN)
        
        buffer = self.products[product_name]
        current_count = len(self.current_kanbans[product_name])
        max_count = buffer.get_max_kanbans()
        
        fill_percentage = current_count / max_count if max_count > 0 else 0.0
        
        # Bestimme höchste Zone
        red_count = sum(1 for z in self.current_kanbans[product_name] if z == Zone.RED)
        yellow_count = sum(1 for z in self.current_kanbans[product_name] if z == Zone.YELLOW)
        
        if red_count > 0:
            current_zone = Zone.RED
        elif yellow_count > 0:
            current_zone = Zone.YELLOW
        else:
            current_zone = Zone.GREEN
        
        return (fill_percentage, current_zone)

    def get_zone_penetration(self, product_name: str) -> float:
        """
        Berechne die Penetration in der aktuell hoechsten Zone.
        Beispiel: Bei Rot -> red_count / red_capacity.
        """
        if product_name not in self.products:
            return 0.0

        buffer = self.products[product_name]
        zones = self.current_kanbans.get(product_name, []) or []
        if not zones:
            return 0.0

        red_count = sum(1 for z in zones if z == Zone.RED)
        yellow_count = sum(1 for z in zones if z == Zone.YELLOW)
        green_count = len(zones) - red_count - yellow_count

        if red_count > 0:
            return red_count / buffer.red_capacity if buffer.red_capacity > 0 else 0.0
        if yellow_count > 0:
            return yellow_count / buffer.yellow_capacity if buffer.yellow_capacity > 0 else 0.0
        if green_count > 0:
            return green_count / buffer.green_capacity if buffer.green_capacity > 0 else 0.0
        return 0.0
    
    def get_priority_ranking(self) -> List[Tuple[str, float, Zone]]:
        """
        Sortiere Produkte nach Priorität für Produktion.
        Regel: Red > Yellow > Green; innerhalb Zone: höherer Füllgrad zuerst

        Rückgabe: [(product_name, fill_percentage, zone), ...]

        Entspricht Folie S. 7: Produkte mit höchstem Level (rot) und höherem
        relativen Füllstand werden bevorzugt.
        """
        ranking = []
        for product_name in self.products:
            fill_pct, zone = self.get_fill_level(product_name)
            zone_penetration = self.get_zone_penetration(product_name)
            ranking.append((product_name, fill_pct, zone, zone_penetration))

        # Sortiere: Zone, dann Penetration in der Zone, dann Gesamt-Fuellgrad.
        zone_priority = {Zone.RED: 3, Zone.YELLOW: 2, Zone.GREEN: 1}
        ranking.sort(key=lambda x: (zone_priority[x[2]], x[3], x[1]), reverse=True)

        return [(name, fill_pct, zone) for name, fill_pct, zone, _ in ranking]
    
    def to_dict(self):
        """Konvertiere zu Dictionary für JSON/Frontend"""
        result = {}
        for name, buffer in self.products.items():
            kanbans = self.current_kanbans.get(name, [])
            green_count = sum(1 for z in kanbans if z == Zone.GREEN)
            yellow_count = sum(1 for z in kanbans if z == Zone.YELLOW)
            red_count = sum(1 for z in kanbans if z == Zone.RED)
            
            fill_pct, current_zone = self.get_fill_level(name)
            
            result[name] = {
                'name': buffer.name,
                'green_cap': buffer.green_capacity,
                'yellow_cap': buffer.yellow_capacity,
                'red_cap': buffer.red_capacity,
                'total_capacity': buffer.get_max_kanbans(),
                'current_total': len(kanbans),
                'green_current': green_count,
                'yellow_current': yellow_count,
                'red_current': red_count,
                'fill_percentage': fill_pct,
                'current_zone': current_zone.value,
                'is_event': buffer.is_event_kanban,
            }
        return result


def load_fg_buffers_from_material_zones() -> Dict[str, ProductBuffer]:
    """Erstelle ProductBuffer fürFG aus material_pufferzonen.csv."""
    material_zones = load_material_buffer_zones()
    fg_names = {'CT5', 'CT6', 'CT7', 'TT6', 'TT7', 'TT8'}
    products: Dict[str, ProductBuffer] = {}
    for name, zones in material_zones.items():
        if name not in fg_names:
            continue
        products[name] = ProductBuffer(
            name=name,
            green_capacity=int(zones['green']),
            yellow_capacity=int(zones['yellow']),
            red_capacity=int(zones['red']),
            total_kanbans=int(zones['total']),
            is_event_kanban=False,
            daily_usage=0.0,
        )
    return products


# ============================================================================
# Loader Functions
# ============================================================================

def load_kanbans_from_csv() -> Dict[str, ProductBuffer]:
    """
    Lade Kanban-Konfiguration aus Demand_Simulation.csv
    """
    csv_path = Path(__file__).parent.parent / 'data' / 'raw' / 'Demand_Simulation.csv'
    
    df = pd.read_csv(csv_path)
    
    products = {}
    for _, row in df.iterrows():
        product_name = row['Produkt'].strip()
        is_event = str(row.get('Event_Kanban', '')).strip().upper() == 'X'
        
        products[product_name] = ProductBuffer(
            name=product_name,
            green_capacity=int(row['Green_Zone']),
            yellow_capacity=int(row['Yellow_Zone']),
            red_capacity=int(row['Red_Zone']),
            total_kanbans=int(row['Total_Kanbans']),
            is_event_kanban=is_event,
            daily_usage=float(row['Durchschnittliche_Nachfrage_täglich'])
        )
    
    return products


def load_buffer_zones_from_csv() -> Dict[str, ProductBuffer]:
    """
    Lade Pufferzonen aus pufferzonen.csv (alternative zu Excel).
    Für RM/SF/FG Komponenten.
    """
    csv_path = Path(__file__).parent.parent / 'data' / 'raw' / 'pufferzonen.csv'
    
    df = pd.read_csv(csv_path, index_col=0)  # Index= Ebene/Beschreibung
    
    # Finde Zeilen mit Zonen-Informationen
    green_zone_row = df.loc['Green Zone [pcs]', 2:]  # Skip erste 2 Spalten
    yellow_zone_row = df.loc['Yellow Zone [pcs]', 2:]
    red_zone_row = df.loc['Total Red Zone [pcs]', 2:]
    
    # Komponenten-Namen (aus Item row)
    komponenten_row = df.loc['Item', 2:]
    
    products = {}
    for i, (name, g, y, r) in enumerate(zip(komponenten_row, green_zone_row, yellow_zone_row, red_zone_row)):
        name = str(name).strip()
        if name and not pd.isna(g):
            products[name] = ProductBuffer(
                name=name,
                green_capacity=int(float(g)),
                yellow_capacity=int(float(y)),
                red_capacity=int(float(r)),
                total_kanbans=int(float(g) + float(y) + float(r)),
                is_event_kanban=False
            )
    
    return products


def load_sf2_buffers_from_material_zones() -> Dict[str, ProductBuffer]:
    """
    Erstelle ProductBuffer fürden SF2-Loop aus material_pufferzonen.csv.
    Verwendet alle Antriebswellen als Produkte.
    """
    material_zones = load_material_buffer_zones()
    products = {}
    for name, zones in material_zones.items():
        if not str(name).startswith('Antriebswelle'):
            continue
        products[name] = ProductBuffer(
            name=name,
            green_capacity=int(zones['green']),
            yellow_capacity=int(zones['yellow']),
            red_capacity=int(zones['red']),
            total_kanbans=int(zones['total']),
            is_event_kanban=False,
            daily_usage=0.0
        )
    return products


# ============================================================================
# Simulation Functions
# ============================================================================

def simulate_daily_consumption(
    overflow_board: OverflowBoard,
    daily_orders: Dict[str, int]
) -> OverflowBoard:
    """
    Simuliere tägliche Verbrauche: Neue Bestellungen -> Kanban-Verbrauch.
    
    Logik (Folie S. 5):
    - Für jedes bestellte Teil: Kanban kommt ins Overflow-Board
    - Beispiel: Kunde bestellt 3 Stück Produkt 1 -> 3 Kanbans ins Board
    """
    for product_name, quantity in daily_orders.items():
        if product_name in overflow_board.products:
            overflow_board.add_kanban(product_name, quantity)
    
    return overflow_board


def calculate_production_schedule(
    overflow_board: OverflowBoard,
    pitch_minutes: int = 30,
    takt_time_seconds: float = 300.0
) -> Dict[str, int]:
    """
    Berechne Produktionsplan für einen Pitch.
    
    Logik (Folie S. 7):
    1. Sortiere Produkte nach Priorität (get_priority_ranking)
    2. Für jedes Produkt: Wieviele Kanbans können in diesem Pitch produziert werden?
       max_units_per_pitch = (pitch_minutes * 60) / takt_time_seconds
    3. Normale Produkte zuerst, Event-Kanbans nur wenn noch Kapazität frei
    """
    available_seconds = pitch_minutes * 60
    production_per_pitch = int(available_seconds / takt_time_seconds)
    
    schedule = {}
    remaining_capacity = production_per_pitch

    # Priorität: get_priority_ranking() sortiert schon richtig
    ranking = overflow_board.get_priority_ranking()
    
    # Normale Produkte zuerst
    for product_name, fill_pct, zone in ranking:
        if remaining_capacity <= 0:
            break
        
        buffer = overflow_board.products[product_name]
        
        # Skip Event-Kanbans in dieser Phase
        if buffer.is_event_kanban:
            continue
        
        # Wieviele Kanbans für dieses Produkt produzieren?
        current_count = len(overflow_board.current_kanbans.get(product_name, []))
        to_produce = min(current_count, remaining_capacity)
        
        if to_produce > 0:
            schedule[product_name] = to_produce
            remaining_capacity -= to_produce
    
    # Event-Kanbans: nur wenn noch Kapazität frei
    for product_name, fill_pct, zone in ranking:
        if remaining_capacity <= 0:
            break
        
        buffer = overflow_board.products[product_name]
        
        # Nur Event-Kanbans
        if not buffer.is_event_kanban:
            continue
        
        current_count = len(overflow_board.current_kanbans.get(product_name, []))
        to_produce = min(current_count, remaining_capacity)
        
        if to_produce > 0:
            schedule[product_name] = to_produce
            remaining_capacity -= to_produce
    
    return schedule


def apply_production_schedule(
    overflow_board: OverflowBoard,
    schedule: Dict[str, int]
) -> OverflowBoard:
    """
    Wende Produktionsplan an: Entferne Kanbans vom Board
    """
    for product_name, quantity in schedule.items():
        overflow_board.remove_kanban(product_name, quantity)
        
        # Tracking
        if product_name not in overflow_board.production_history:
            overflow_board.production_history[product_name] = []
        overflow_board.production_history[product_name].append(quantity)
    
    return overflow_board


def _clone_board_for_schedule(board: OverflowBoard) -> OverflowBoard:
    if board is None:
        return None
    cloned = OverflowBoard(products=board.products)
    for product, zones in board.current_kanbans.items():
        cloned.current_kanbans[product] = list(zones)
    return cloned


def load_max_kanbans_per_pitch(loop_name: str) -> Dict[str, int]:
    """Load max kanbans per pitch from CSV for loop A/B."""
    file_map = {
        'A': 'data/LoopA_Pitch_Analysis.csv',
        'B': 'data/LoopB_Pitch_Analysis.csv'
    }
    csv_path = Path(__file__).parent.parent / file_map.get(loop_name, '')
    if not csv_path.exists():
        return {}
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return {}

    if df.empty or 'Produkt' not in df.columns or 'Maximum number of Kanbans per Pitch' not in df.columns:
        return {}

    max_map = {}
    for _, row in df.iterrows():
        product = str(row.get('Produkt', '')).strip()
        if not product or product.lower() == 'summe':
            continue
        qty = row.get('Maximum number of Kanbans per Pitch')
        try:
            max_map[product] = int(float(qty))
        except Exception:
            continue
    if loop_name == 'A':
        remap = {
            'Antriebswelle 5': 'Antriebswelle (5-Gang)',
            'Antriebswelle 6': 'Antriebswelle (6-Gang)',
            'Antriebswelle 7': 'Antriebswelle (7-Gang)',
            'Antriebswelle 8': 'Antriebswelle (8-Gang)'
        }
        max_map = {remap.get(k, k): v for k, v in max_map.items()}
    return max_map


def _normalize_mix_weights(
    board: OverflowBoard,
    mix_weights: Dict[str, float] | None,
) -> Dict[str, float] | None:
    """Normalize mix weights for heijunka slot selection."""
    if mix_weights is None:
        return None
    weights = {}
    for name in board.products.keys():
        raw = mix_weights.get(name, 0)
        try:
            weight = float(raw)
        except Exception:
            weight = 0.0
        if weight <= 0 and board.current_kanbans.get(name):
            weight = 1.0
        weights[name] = weight
    if not any(w > 0 for w in weights.values()):
        return None
    return weights


def build_slot_schedule_full_day(
    board: OverflowBoard,
    slots_per_day: int = 32,
    max_per_pitch: dict = None,
    mix_weights: Dict[str, float] | None = None,
) -> dict:
    """Heijunka-Slot-Planung ueber den Tag (Prioritaetslogik + Mix)."""
    slot_plan = {name: [] for name in board.products.keys()}
    max_per_pitch = max_per_pitch or {}
    mix_weights = _normalize_mix_weights(board, mix_weights)
    produced_slots = {name: 0 for name in board.products.keys()} if mix_weights else {}

    abc_xyz = {
        "TT6": ("A", "Y"),
        "TT7": ("B", "Y"),
        "TT8": ("B", "Y"),
        "CT6": ("C", "X"),
        "CT5": ("C", "X"),
        "CT7": ("C", "Z"),
    }
    abc_rank = {"A": 0, "B": 1, "C": 2}
    xyz_rank = {"X": 0, "Y": 1, "Z": 2}

    def product_priority_key(name: str) -> tuple:
        abc, xyz = abc_xyz.get(name, ("C", "Z"))
        return (abc_rank.get(abc, 9), xyz_rank.get(xyz, 9), name)

    def highest_zone(name: str):
        zones = board.current_kanbans.get(name, []) or []
        if any(z == Zone.RED for z in zones):
            return Zone.RED
        if any(z == Zone.YELLOW for z in zones):
            return Zone.YELLOW
        if zones:
            return Zone.GREEN
        return None

    def zone_rank(z):
        if z == Zone.RED:
            return 0
        if z == Zone.YELLOW:
            return 1
        if z == Zone.GREEN:
            return 2
        return 9

    def zone_penetration(name: str) -> float:
        zones = board.current_kanbans.get(name, []) or []
        if not zones:
            return 0.0
        buffer = board.products[name]
        red_count = sum(1 for z in zones if z == Zone.RED)
        yellow_count = sum(1 for z in zones if z == Zone.YELLOW)
        green_count = len(zones) - red_count - yellow_count
        if red_count > 0:
            return red_count / buffer.red_capacity if buffer.red_capacity > 0 else 0.0
        if yellow_count > 0:
            return yellow_count / buffer.yellow_capacity if buffer.yellow_capacity > 0 else 0.0
        if green_count > 0:
            return green_count / buffer.green_capacity if buffer.green_capacity > 0 else 0.0
        return 0.0

    def mix_deficit(name: str, pool: List[str], slot_idx: int) -> float | None:
        if not mix_weights:
            return None
        total_weight = sum(mix_weights.get(p, 0.0) for p in pool)
        if total_weight <= 0:
            return None
        weight = mix_weights.get(name, 0.0)
        desired = (slot_idx + 1) * weight / total_weight
        return desired - produced_slots.get(name, 0)

    last_product = None
    for slot_idx in range(slots_per_day):
        candidates = [name for name in board.products.keys() if board.current_kanbans.get(name)]
        if not candidates:
            break

        candidate_zones = {name: highest_zone(name) for name in candidates}
        best_zone = min((z for z in candidate_zones.values() if z is not None), key=zone_rank)

        in_zone = [name for name in candidates if candidate_zones.get(name) == best_zone]
        normal = [n for n in in_zone if not board.products[n].is_event_kanban]
        pool = normal if normal else in_zone

        def choose_key(name: str) -> tuple:
            mix_gap = mix_deficit(name, pool, slot_idx)
            mix_key = -mix_gap if mix_gap is not None else 0.0
            return (-zone_penetration(name), mix_key, *product_priority_key(name), 0 if name == last_product else 1)

        remaining_pool = list(pool)
        chosen = None
        while remaining_pool:
            candidate = sorted(remaining_pool, key=choose_key)[0]
            available = len(board.current_kanbans.get(candidate, []))
            if candidate in ("CT5", "TT6") and available < 2:
                remaining_pool = [p for p in remaining_pool if p != candidate]
                continue
            chosen = candidate
            break
        if chosen is None:
            break

        planned_qty = 2 if chosen in ("CT5", "TT6") else 1
        max_per = max(1, max_per_pitch.get(chosen, planned_qty))
        planned_qty = min(planned_qty, max_per)
        available = len(board.current_kanbans.get(chosen, []))
        removable = min(planned_qty, available)
        if removable > 0:
            board.remove_kanban(chosen, removable)
            slot_plan[chosen].extend([slot_idx] * removable)
            if mix_weights:
                produced_slots[chosen] = produced_slots.get(chosen, 0) + 1

        last_product = chosen

    return slot_plan


def build_slot_schedule_full_day_with_replenishment(
    board: OverflowBoard,
    repl_qty_map: dict,
    slots_per_day: int = 20,
    max_per_pitch: dict = None,
    mix_weights: Dict[str, float] | None = None,
) -> dict:
    """Priorisiert Replenishment Qty > 0 und faellt danach auf Standard-Prioritaet + Mix."""
    slot_plan = {name: [] for name in board.products.keys()}
    max_per_pitch = max_per_pitch or {}
    mix_weights = _normalize_mix_weights(board, mix_weights)
    produced_slots = {name: 0 for name in board.products.keys()} if mix_weights else {}
    if not repl_qty_map:
        return build_slot_schedule_full_day(board, slots_per_day, max_per_pitch, mix_weights)

    repl_remaining = dict(repl_qty_map)

    abc_xyz = {
        "TT6": ("A", "Y"),
        "TT7": ("B", "Y"),
        "TT8": ("B", "Y"),
        "CT6": ("C", "X"),
        "CT5": ("C", "X"),
        "CT7": ("C", "Z"),
    }
    abc_rank = {"A": 0, "B": 1, "C": 2}
    xyz_rank = {"X": 0, "Y": 1, "Z": 2}

    def product_priority_key(name: str) -> tuple:
        abc, xyz = abc_xyz.get(name, ("C", "Z"))
        return (abc_rank.get(abc, 9), xyz_rank.get(xyz, 9), name)

    def highest_zone(name: str):
        zones = board.current_kanbans.get(name, []) or []
        if any(z == Zone.RED for z in zones):
            return Zone.RED
        if any(z == Zone.YELLOW for z in zones):
            return Zone.YELLOW
        if zones:
            return Zone.GREEN
        return None

    def zone_rank(z):
        if z == Zone.RED:
            return 0
        if z == Zone.YELLOW:
            return 1
        if z == Zone.GREEN:
            return 2
        return 9

    def zone_penetration(name: str) -> float:
        zones = board.current_kanbans.get(name, []) or []
        if not zones:
            return 0.0
        buffer = board.products[name]
        red_count = sum(1 for z in zones if z == Zone.RED)
        yellow_count = sum(1 for z in zones if z == Zone.YELLOW)
        green_count = len(zones) - red_count - yellow_count
        if red_count > 0:
            return red_count / buffer.red_capacity if buffer.red_capacity > 0 else 0.0
        if yellow_count > 0:
            return yellow_count / buffer.yellow_capacity if buffer.yellow_capacity > 0 else 0.0
        if green_count > 0:
            return green_count / buffer.green_capacity if buffer.green_capacity > 0 else 0.0
        return 0.0

    def mix_deficit(name: str, pool: List[str], slot_idx: int) -> float | None:
        if not mix_weights:
            return None
        total_weight = sum(mix_weights.get(p, 0.0) for p in pool)
        if total_weight <= 0:
            return None
        weight = mix_weights.get(name, 0.0)
        desired = (slot_idx + 1) * weight / total_weight
        return desired - produced_slots.get(name, 0)

    last_product = None
    for slot_idx in range(slots_per_day):
        exclude = set()
        chosen = None
        while True:
            candidates = [p for p, qty in repl_remaining.items() if qty > 0 and board.current_kanbans.get(p) and p not in exclude]
            if candidates:
                def repl_choose_key(name: str) -> tuple:
                    mix_gap = mix_deficit(name, candidates, slot_idx)
                    mix_key = -mix_gap if mix_gap is not None else 0.0
                    return (-repl_remaining.get(name, 0), mix_key, *product_priority_key(name), 0 if name == last_product else 1)

                chosen = sorted(candidates, key=repl_choose_key)[0]
            else:
                ranking = board.get_priority_ranking()
                pool = []
                top_zone = None
                for name, _, zone in ranking:
                    if name in exclude:
                        continue
                    if board.products[name].is_event_kanban:
                        continue
                    if not board.current_kanbans.get(name):
                        continue
                    if top_zone is None:
                        top_zone = zone
                    if zone != top_zone:
                        break
                    pool.append(name)
                if not pool:
                    for name, _, zone in ranking:
                        if name in exclude:
                            continue
                        if not board.current_kanbans.get(name):
                            continue
                        if top_zone is None:
                            top_zone = zone
                        if zone != top_zone:
                            break
                        pool.append(name)
                if pool:
                    def choose_key(name: str) -> tuple:
                        mix_gap = mix_deficit(name, pool, slot_idx)
                        mix_key = -mix_gap if mix_gap is not None else 0.0
                        return (-zone_penetration(name), mix_key, *product_priority_key(name), 0 if name == last_product else 1)

                    chosen = sorted(pool, key=choose_key)[0]
                else:
                    chosen = None
            if chosen is None:
                break
            available = len(board.current_kanbans.get(chosen, []))
            if chosen in ("CT5", "TT6") and available < 2:
                exclude.add(chosen)
                chosen = None
                continue
            break

        if chosen is None:
            break

        default_max = 2 if chosen in ("CT5", "TT6") else 1
        max_per = max_per_pitch.get(chosen, default_max)
        available = len(board.current_kanbans.get(chosen, []))
        to_make = max(1, min(max_per, available))
        board.remove_kanban(chosen, to_make)
        slot_plan[chosen].extend([slot_idx] * to_make)
        if mix_weights:
            produced_slots[chosen] = produced_slots.get(chosen, 0) + 1
        if chosen in repl_remaining:
            repl_remaining[chosen] = max(0, repl_remaining[chosen] - to_make)

        last_product = chosen

    return slot_plan


def _schedule_counts_from_slots(schedule_slots: Dict[str, List[int]]) -> Dict[str, int]:
    counts = {}
    for product, slots in (schedule_slots or {}).items():
        counts[product] = len(slots)
    return counts


# ============================================================================
# Daily Simulation Engine - für globale Tagessprünge
# ============================================================================

@dataclass
class MaterialConsumptionState:
    """Speichert Materialverbrauch pro Tag für Tracking"""
    daily_consumption: Dict[int, Dict[str, int]] = field(default_factory=dict)  # Tag -> Materialverbrauch
    cumulative_consumption: Dict[str, int] = field(default_factory=dict)  # Gesamtverbrauch
    
    def record_day(self, day: int, consumption: Dict[str, int]):
        """Speichere Verbrauch für einen Tag"""
        self.daily_consumption[day] = consumption
        
        for material, qty in consumption.items():
            if material not in self.cumulative_consumption:
                self.cumulative_consumption[material] = 0
            self.cumulative_consumption[material] += qty
    
    def to_dict(self):
        """Serialisiere für JSON/Frontend"""
        return {
            'daily': self.daily_consumption,
            'cumulative': self.cumulative_consumption
        }


@dataclass
class FinancialHistoryState:
    """Speichert Finanzhistorie pro Tag für Tracking"""
    daily_financials: Dict[int, Dict[str, float]] = field(default_factory=dict)  # Tag -> Finanzdaten
    
    def record_day(self, day: int, financials: Dict[str, float]):
        """Speichere Finanzdaten für einen Tag"""
        self.daily_financials[day] = financials
    
    def get_totals(self) -> Dict[str, float]:
        """Berechne Gesamtsummen über alle Tage"""
        total_revenue = sum(d.get('revenue', 0) for d in self.daily_financials.values())
        total_cost = sum(d.get('cost', 0) for d in self.daily_financials.values())
        total_profit = sum(d.get('profit', 0) for d in self.daily_financials.values())
        total_products = sum(d.get('products_sold', 0) for d in self.daily_financials.values())
        avg_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        return {
            'total_revenue': total_revenue,
            'total_cost': total_cost,
            'total_profit': total_profit,
            'total_products': total_products,
            'avg_margin': avg_margin
        }
    
    def to_list(self) -> List[Dict[str, float]]:
        """Konvertiere zu sortierter Liste für Charts"""
        return [self.daily_financials[day] for day in sorted(self.daily_financials.keys())]
    
    def to_dict(self):
        """Serialisiere für JSON/Frontend"""
        return {
            'daily': self.daily_financials,
            'totals': self.get_totals()
        }


@dataclass
class SimulationState:
    """Speichert den aktuellen Simulationszustand über mehrere Tage"""
    current_day: int = 1
    board: OverflowBoard = None
    board_a: OverflowBoard = None
    daily_orders_history: List[Dict[str, int]] = field(default_factory=list)
    daily_production_history: List[Dict[str, int]] = field(default_factory=list)
    daily_production_history_a: List[Dict[str, int]] = field(default_factory=list)
    daily_replenishment_history: List[Dict[str, int]] = field(default_factory=list)
    daily_replenishment_history_a: List[Dict[str, int]] = field(default_factory=list)
    daily_replenishment_cards_history: List[List[Dict[str, object]]] = field(default_factory=list)
    daily_replenishment_cards_history_a: List[List[Dict[str, object]]] = field(default_factory=list)
    daily_production_executed: List[Dict[str, int]] = field(default_factory=list)
    daily_production_executed_a: List[Dict[str, int]] = field(default_factory=list)
    daily_production_shortages: List[Dict[str, Dict[str, int]]] = field(default_factory=list)
    daily_production_shortages_a: List[Dict[str, Dict[str, int]]] = field(default_factory=list)
    production_executed_days: List[int] = field(default_factory=list)
    heijunka_planned_day_b: int = 0
    heijunka_planned_day_a: int = 0
    material_consumption: MaterialConsumptionState = field(default_factory=MaterialConsumptionState)
    booked_material_consumption: MaterialConsumptionState = field(default_factory=MaterialConsumptionState)
    financial_history: FinancialHistoryState = field(default_factory=FinancialHistoryState)
    pending_material_consumption: Dict[str, int] = field(default_factory=dict)
    pending_fg_demand: Dict[str, int] = field(default_factory=dict)
    pending_on_order_b: Dict[str, int] = field(default_factory=dict)
    pending_on_order_a: Dict[str, int] = field(default_factory=dict)
    planned_snapshot_b: Dict[str, int] = field(default_factory=dict)
    planned_snapshot_a: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self):
        """Serialisiere für JSON/Frontend"""
        return {
            'current_day': self.current_day,
            'board_state': self.board.to_dict() if self.board else {},
            'board_a_state': self.board_a.to_dict() if self.board_a else {},
            'daily_orders_count': len(self.daily_orders_history),
            'daily_production_count': len(self.daily_production_history),
            'daily_production_count_a': len(self.daily_production_history_a),
            'daily_replenishment_count': len(self.daily_replenishment_history),
            'daily_replenishment_count_a': len(self.daily_replenishment_history_a),
            'material_consumption': self.material_consumption.to_dict(),
            'financial_history': self.financial_history.to_dict(),
        }


def load_or_create_simulation_state() -> SimulationState:
    """
    Lade existierende Simulationszustand oder erstelle neuen.
    Der Zustand wird in 'data/simulation_state.pkl' gespeichert.
    """
    import pickle
    from pathlib import Path
    
    state_file = Path(__file__).parent.parent / 'data' / 'simulation_state.pkl'
    
    if state_file.exists():
        try:
            with open(state_file, 'rb') as f:
                state = pickle.load(f)
                # Kompatibilität: Falls alte State keine material_consumption hat, initialisiere
                if not hasattr(state, 'material_consumption'):
                    state.material_consumption = MaterialConsumptionState()
                if not hasattr(state, 'booked_material_consumption'):
                    state.booked_material_consumption = MaterialConsumptionState()
                # Kompatibilität: Falls alte State keine financial_history hat, initialisiere
                if not hasattr(state, 'financial_history'):
                    state.financial_history = FinancialHistoryState()
                # Kompatibilität: Falls alte State keine Loop-A Board hat, initialisiere
                if not hasattr(state, 'board_a') or state.board_a is None:
                    products_a = load_sf2_buffers_from_material_zones()
                    state.board_a = OverflowBoard(products=products_a)
                if not hasattr(state, 'daily_production_history_a'):
                    state.daily_production_history_a = []
                if not hasattr(state, 'daily_replenishment_history'):
                    state.daily_replenishment_history = []
                if not hasattr(state, 'daily_replenishment_history_a'):
                    state.daily_replenishment_history_a = []
                if not hasattr(state, 'daily_replenishment_cards_history'):
                    state.daily_replenishment_cards_history = []
                if not hasattr(state, 'daily_replenishment_cards_history_a'):
                    state.daily_replenishment_cards_history_a = []
                if not hasattr(state, 'planned_snapshot_b'):
                    state.planned_snapshot_b = {}
                if not hasattr(state, 'planned_snapshot_a'):
                    state.planned_snapshot_a = {}
                if not hasattr(state, 'daily_production_executed'):
                    state.daily_production_executed = []
                if not hasattr(state, 'daily_production_executed_a'):
                    state.daily_production_executed_a = []
                if not hasattr(state, 'daily_production_shortages'):
                    state.daily_production_shortages = []
                if not hasattr(state, 'daily_production_shortages_a'):
                    state.daily_production_shortages_a = []
                if not hasattr(state, 'production_executed_days'):
                    state.production_executed_days = []
                if not hasattr(state, 'heijunka_planned_day_b'):
                    state.heijunka_planned_day_b = 0
                if not hasattr(state, 'heijunka_planned_day_a'):
                    state.heijunka_planned_day_a = 0
                if not hasattr(state, 'pending_on_order_b'):
                    state.pending_on_order_b = {}
                if not hasattr(state, 'pending_on_order_a'):
                    state.pending_on_order_a = {}

                # Kompatibilität/Alignment: Loop-B Board soll FG aus material_pufferzonen nutzen
                try:
                    fg_products = load_fg_buffers_from_material_zones()
                    if not hasattr(state, 'board') or state.board is None:
                        state.board = OverflowBoard(products=fg_products)
                    else:
                        fg_names = set(fg_products.keys())
                        existing_names = set(getattr(state.board, 'products', {}).keys())
                        if existing_names != fg_names:
                            old_counts = {k: len(v) for k, v in getattr(state.board, 'current_kanbans', {}).items()}
                            new_board = OverflowBoard(products=fg_products)
                            for prod in fg_names:
                                new_board.add_kanban(prod, int(old_counts.get(prod, 0)))
                            state.board = new_board
                except Exception:
                    pass
                return state
        except (EOFError, pickle.UnpicklingError, Exception) as e:
            # Korrupte Datei - lösche und erstelle neu
            print(f"[WARN] Korrupte Simulationsdatei gefunden, erstelle neu: {e}")
            try:
                state_file.unlink()
            except PermissionError:
                pass
    
    # Erstelle neuen Zustand
    products = load_fg_buffers_from_material_zones()
    board = OverflowBoard(products=products)
    products_a = load_sf2_buffers_from_material_zones()
    board_a = OverflowBoard(products=products_a)
    state = SimulationState(current_day=1, board=board, board_a=board_a)
    save_simulation_state(state)
    return state


def _compute_replenishment_cards(
    *,
    products: Dict[str, ProductBuffer],
    board: OverflowBoard,
    on_hand: Dict[str, int],
    demand: Dict[str, int],
    zones: Dict[str, Dict[str, int]],
    on_order: Dict[str, int] = None,
) -> Tuple[Dict[str, int], List[Dict[str, object]]]:
    """NFP = OnHand - Demand; Trigger: NFP <= ToY; Repl = ToG - NFP."""
    replenishment: Dict[str, int] = {}
    cards: List[Dict[str, object]] = []
    on_order = on_order or {}
    for name in products.keys():
        z = zones.get(name)
        if not z:
            continue

        toy = int(z.get('red', 0) + z.get('yellow', 0))
        tog = int(z.get('total', 0))

        oh = int(on_hand.get(name, 0))
        oo = int(on_order.get(name, 0))
        dem = int(demand.get(name, 0))

        nfp = int(oh + oo - dem)
        trigger = bool(nfp <= toy)
        repl = int(max(0, tog - nfp)) if trigger else 0

        replenishment[name] = repl
        cards.append({
            'material': name,
            'on_hand': oh,
            'on_order': oo,
            'demand': dem,
            'net_flow': nfp,
            'to_y': toy,
            'to_g': tog,
            'trigger': trigger,
            'replenishment_qty': repl,
        })

    return replenishment, cards


def _snapshot_from_board(board: OverflowBoard) -> Dict[str, int]:
    if not board:
        return {}
    snapshot: Dict[str, int] = {}
    for product in board.products.keys():
        snapshot[product] = len(board.current_kanbans.get(product, []))
    return snapshot


def _missing_from_snapshot_and_shortages(
    planned_snapshot: Dict[str, int],
    fallback_planned: Dict[str, int],
    executed: Dict[str, int],
    shortages: Dict[str, Dict[str, int]],
) -> Dict[str, int]:
    missing_map: Dict[str, int] = {}
    planned_base = planned_snapshot or fallback_planned or {}
    products = set(planned_base.keys()) | set((executed or {}).keys()) | set((shortages or {}).keys())
    for product in products:
        short_info = (shortages or {}).get(product)
        if short_info:
            missing = int((short_info or {}).get('missing', 0) or 0)
        else:
            planned_qty = int(planned_base.get(product, 0) or 0)
            executed_qty = int((executed or {}).get(product, 0) or 0)
            missing = max(0, planned_qty - executed_qty)
        if missing > 0:
            missing_map[product] = missing
    return missing_map


def save_simulation_state(state: SimulationState):
    """Speichere Simulationszustand"""
    import pickle
    from pathlib import Path
    
    state_file = Path(__file__).parent.parent / 'data' / 'simulation_state.pkl'
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(state_file, 'wb') as f:
        pickle.dump(state, f)


def load_simulated_orders_for_day(day: int) -> Dict[str, int]:
    """
    Lade vorausberechnete Bestellungen für einen bestimmten Tag aus simulated_orders.csv.
    Falls keine Daten für diesen Tag existieren, return None.
    
    Args:
        day: Tag für den Bestellungen geladen werden sollen
        
    Returns:
        Dict mit Produkten und Mengen oder None wenn nicht vorhanden
    """
    csv_path = Path(__file__).parent.parent / 'data' / 'simulated_orders.csv'
    
    if not csv_path.exists():
        return None
    
    try:
        df = pd.read_csv(csv_path)
        
        if df.empty or 'Day' not in df.columns:
            return None
        
        # Finde Zeile für diesen Tag
        day_data = df[df['Day'] == day]
        
        if day_data.empty:
            return None
        
        # Konvertiere Zeile zu Dict (ohne Day-Spalte)
        row = day_data.iloc[0]
        orders = {}
        for col in df.columns:
            if col != 'Day':
                value = row[col]
                if pd.notna(value) and value > 0:
                    orders[col] = int(value)
        
        return orders if orders else None
    except Exception as e:
        print(f"Fehler beim Laden der simulierten Bestellungen: {e}")
        return None


def _load_fg_daily_demand_means() -> Dict[str, float]:
    """Lädt erwartete tägliche Nachfrage (Mean) pro FG-Produkt.

    Primärquelle: data/raw/Demand_Simulation.csv (Spalte 'Durchschnittliche_Nachfrage_täglich').
    Fallback: einfache Defaults, falls Datei fehlt.
    """
    fg_names = ['CT5', 'CT6', 'CT7', 'TT6', 'TT7', 'TT8']
    csv_path = Path(__file__).parent.parent / 'data' / 'raw' / 'Demand_Simulation.csv'

    defaults = {'CT5': 16.28, 'CT6': 3.08, 'CT7': 4.32, 'TT6': 14.04, 'TT7': 5.18, 'TT8': 0.87}
    if not csv_path.exists():
        return {k: float(defaults.get(k, 0.0)) for k in fg_names}

    try:
        try:
            df = pd.read_csv(csv_path, encoding='utf-8-sig')
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, encoding='cp1252')
        means: Dict[str, float] = {}

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
            'Durchschnittliche_Nachfrage_täglich',
            'Durchschnittliche_Nachfrage_taeglich',
        )
        mean_col = next((c for c in mean_col_candidates if c in df.columns), None)

        for _, row in df.iterrows():
            name = str(row.get('Produkt', '')).strip()
            if name in fg_names:
                raw = row.get(mean_col) if mean_col else None
                means[name] = _to_float(raw, float(defaults.get(name, 0.0)))
        for name in fg_names:
            means.setdefault(name, float(defaults.get(name, 0.0)))
        return means
    except Exception:
        return {k: float(defaults.get(k, 0.0)) for k in fg_names}


def _generate_random_fg_orders_for_day(
    day: int,
    *,
    prev_orders: Dict[str, int] | None = None,
    apply_smoothing: bool = False,
) -> Dict[str, int]:
    """Erzeuge zufällige Bestellungen für FG (Loop B).

    Wichtig: Das ist *die* Nachfragequelle, wenn keine vorab festgelegte Simulation
    in data/simulated_orders.csv vorliegt.
    """
    from utils.demand_simulator import poisson_generator

    means = _load_fg_daily_demand_means()
    orders: Dict[str, int] = {}
    for product, mean in means.items():
        lam = max(0.0, float(mean))
        raw = poisson_generator(lam) if lam > 0 else 0
        qty = float(raw)
        if apply_smoothing:
            prev = float(lam)
            if prev_orders and product in prev_orders:
                try:
                    prev = float(prev_orders.get(product, lam) or 0.0)
                except Exception:
                    prev = float(lam)
            qty = 0.7 * prev + 0.3 * raw
        qty = int(round(qty))
        if qty > 0:
            orders[product] = int(qty)
    return orders


def _upsert_simulated_orders_row(day: int, orders: Dict[str, int]) -> None:
    """Schreibt eine Tageszeile in data/simulated_orders.csv (append oder update).

    Dadurch bleibt die zufällige Nachfrage reproduzierbar innerhalb eines Runs,
    und UI/Heijunka sehen konsistente Werte.
    """
    csv_path = Path(__file__).parent.parent / 'data' / 'simulated_orders.csv'
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    columns = ['Day', 'CT5', 'CT6', 'CT7', 'TT6', 'TT7', 'TT8']
    try:
        if csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            df = pd.DataFrame(columns=columns)
    except Exception:
        df = pd.DataFrame(columns=columns)

    if df.empty or 'Day' not in df.columns:
        df = pd.DataFrame(columns=columns)

    # Ensure required columns exist
    for col in columns:
        if col not in df.columns:
            df[col] = 0

    row = {'Day': int(day)}
    for col in columns:
        if col == 'Day':
            continue
        row[col] = int(orders.get(col, 0) or 0)

    mask = (df['Day'] == int(day)) if not df.empty else None
    if mask is not None and mask.any():
        for col, val in row.items():
            df.loc[mask, col] = val
    else:
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)

    df = df[columns].sort_values('Day')
    df.to_csv(csv_path, index=False)


def get_or_generate_orders_for_day(
    day: int,
    *,
    prev_orders: Dict[str, int] | None = None,
    apply_smoothing_on_generate: bool = False,
) -> Dict[str, int]:
    """Liefert Bestellungen für einen Tag.

    - Wenn in simulated_orders.csv vorhanden: nutzen.
    - Sonst: zufällig generieren und in simulated_orders.csv persistieren.
    """
    existing = load_simulated_orders_for_day(day)
    if existing is not None:
        return existing
    generated = _generate_random_fg_orders_for_day(
        day,
        prev_orders=prev_orders,
        apply_smoothing=apply_smoothing_on_generate,
    )
    _upsert_simulated_orders_row(day, generated)
    return generated


def get_max_simulated_day() -> int:
    """
    Ermittle den höchsten vorausberechneten Tag in simulated_orders.csv.
    
    Returns:
        Höchster Tag oder 0 wenn keine Simulation vorhanden
    """
    csv_path = Path(__file__).parent.parent / 'data' / 'simulated_orders.csv'
    
    if not csv_path.exists():
        return 0
    
    try:
        df = pd.read_csv(csv_path)
        if df.empty or 'Day' not in df.columns:
            return 0
        return int(df['Day'].max())
    except:
        return 0


def apply_pending_demand(state: SimulationState) -> None:
    """Buche aufgeschobenen Demand in den Material-Fuellstaenden."""
    pending_material = state.pending_material_consumption or {}
    if not pending_material:
        return

    fill_levels = load_or_create_material_fill_levels()
    for material, consumed_qty in pending_material.items():
        if material in fill_levels:
            fill_levels[material] = max(0, fill_levels[material] - consumed_qty)

    save_material_fill_levels(fill_levels)
    day = state.current_day
    booked = state.booked_material_consumption
    daily = dict(booked.daily_consumption.get(day, {}))
    for material, consumed_qty in pending_material.items():
        daily[material] = daily.get(material, 0) + consumed_qty
        booked.cumulative_consumption[material] = booked.cumulative_consumption.get(material, 0) + consumed_qty
    booked.daily_consumption[day] = daily
    state.pending_material_consumption = {}


def apply_pending_fg_demand(state: SimulationState) -> None:
    """Buche aufgeschobenen FG-Demand in den Material-Fuellstaenden."""
    pending_fg = state.pending_fg_demand or {}
    if not pending_fg:
        return

    fill_levels = load_or_create_material_fill_levels()
    for product_id, qty in pending_fg.items():
        if product_id in fill_levels:
            fill_levels[product_id] = max(0, fill_levels[product_id] - qty)

    save_material_fill_levels(fill_levels)
    state.pending_fg_demand = {}




def _get_bom_components(bom_df: pd.DataFrame, product: str) -> List[Tuple[str, int]]:
    """Return BOM components as (component, qty_per) for a product."""
    if bom_df is None or product is None:
        return []
    product_bom = bom_df[bom_df['Product'] == product]
    components = []
    for _, row in product_bom.iterrows():
        component = row['Component']
        qty_val = row['Quantity']
        qty_per = int(qty_val) if qty_val == qty_val else 0
        if qty_per > 0:
            components.append((component, qty_per))
    return components


def _limit_by_components(fill_levels: Dict[str, int], components: List[Tuple[str, int]], planned_qty: int) -> Tuple[int, str]:
    """Return (max_qty, limiting_component) based on available components."""
    if planned_qty <= 0:
        return 0, ''
    limit = planned_qty
    limiting_component = ''
    for component, qty_per in components:
        available = int(fill_levels.get(component, 0))
        possible = available // qty_per if qty_per > 0 else 0
        if possible < limit:
            limit = possible
            limiting_component = component
    return max(0, limit), limiting_component


def _execute_production_schedule(
    schedule: Dict[str, int],
    fill_levels: Dict[str, int],
    bom_df: pd.DataFrame,
) -> Tuple[Dict[str, int], Dict[str, Dict[str, int]], Dict[str, int]]:
    """Execute schedule with component constraints and update fill levels."""
    executed: Dict[str, int] = {}
    shortages: Dict[str, Dict[str, int]] = {}
    consumption: Dict[str, int] = {}
    if not schedule:
        return executed, shortages, consumption

    for product in sorted(schedule.keys()):
        planned = int(schedule.get(product, 0) or 0)
        if planned <= 0:
            continue
        components = _get_bom_components(bom_df, product)
        max_qty, limiting_component = _limit_by_components(fill_levels, components, planned)
        actual = min(planned, max_qty)
        if actual <= 0:
            shortages[product] = {
                'planned': planned,
                'executed': 0,
                'missing': planned,
                'limit': limiting_component
            }
            continue

        for component, qty_per in components:
            used = actual * qty_per
            if used <= 0:
                continue
            fill_levels[component] = max(0, int(fill_levels.get(component, 0)) - used)
            consumption[component] = consumption.get(component, 0) + used

        fill_levels[product] = int(fill_levels.get(product, 0)) + actual
        executed[product] = actual
        if actual < planned:
            shortages[product] = {
                'planned': planned,
                'executed': actual,
                'missing': planned - actual,
                'limit': limiting_component
            }

    return executed, shortages, consumption


def _ensure_sf3_min_stock(
    fill_levels: Dict[str, int],
    plan_b: Dict[str, int],
    slots_per_day: int = 20,
) -> int:
    sf3_name = 'Betriebsgehäuse'
    max_per_pitch = load_max_kanbans_per_pitch('B')
    max_per_pitch_default = max(max_per_pitch.values()) if max_per_pitch else 1
    slots_per_shift = max(1, slots_per_day // 2)
    min_stock = slots_per_shift * max_per_pitch_default
    planned_total = sum(int(qty or 0) for qty in (plan_b or {}).values())
    target = max(min_stock, planned_total)
    current = int(fill_levels.get(sf3_name, 0))
    if current < target:
        fill_levels[sf3_name] = target
        return target - current
    return 0


def _compute_loop_b_repl_qty_map(
    board: OverflowBoard,
    daily_orders: Dict[str, int],
    fill_levels: Dict[str, int],
    material_zones: Dict[str, Dict[str, int]],
) -> Dict[str, int]:
    repl_qty_map = {}
    for prod in board.products.keys():
        zones = material_zones.get(prod)
        if not zones:
            continue
        on_hand = int(fill_levels.get(prod, 0))
        on_order = len(board.current_kanbans.get(prod, []))
        demand = int(daily_orders.get(prod, 0))
        net_flow = on_hand + on_order - demand
        toy = int(zones['red'] + zones['yellow'])
        if net_flow <= toy:
            repl_qty = max(0, int(zones['total']) - net_flow)
            if repl_qty > 0:
                repl_qty_map[prod] = repl_qty
    return repl_qty_map


def compute_heijunka_plan_counts(
    board_b: OverflowBoard,
    board_a: OverflowBoard,
    daily_orders: Dict[str, int],
    slots_per_day_b: int = 20,
    slots_per_day_a: int = 26,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    material_zones = load_material_buffer_zones()
    fill_levels = load_or_create_material_fill_levels()
    mix_weights_b = dict(daily_orders or {})
    mix_weights_a = get_sf2_orders_from_fg_orders(daily_orders or {})

    plan_b = {}
    if board_b:
        repl_qty_map = _compute_loop_b_repl_qty_map(board_b, daily_orders, fill_levels, material_zones)
        board_b_copy = OverflowBoard(products=board_b.products)
        for product, zones in board_b.current_kanbans.items():
            board_b_copy.add_kanban(product, len(zones))
        schedule_slots_b = build_slot_schedule_full_day_with_replenishment(
            board_b_copy,
            repl_qty_map,
            slots_per_day=slots_per_day_b,
            max_per_pitch=load_max_kanbans_per_pitch('B'),
            mix_weights=mix_weights_b,
        )
        plan_b = _schedule_counts_from_slots(schedule_slots_b)

    plan_a = {}
    if board_a:
        board_a_copy = _clone_board_for_schedule(board_a)
        schedule_slots_a = build_slot_schedule_full_day(
            board_a_copy,
            slots_per_day=slots_per_day_a,
            mix_weights=mix_weights_a,
        )
        plan_a = _schedule_counts_from_slots(schedule_slots_a)

    return plan_b, plan_a


def execute_production_for_today(state: SimulationState) -> Dict[str, object]:
    """Execute production for the current day with component constraints."""
    day = state.current_day
    if day in getattr(state, 'production_executed_days', []):
        return {
            'status': 'already',
            'message': f'Produktion für Tag {day} wurde bereits gebucht.'
        }

    bom_df = load_bom_from_csv()
    fill_levels = load_or_create_material_fill_levels()

    plan_a = state.daily_production_history_a[-1] if state.daily_production_history_a else {}
    plan_b = state.daily_production_history[-1] if state.daily_production_history else {}
    if not plan_a or not plan_b:
        daily_orders = state.daily_orders_history[-1] if state.daily_orders_history else {}
        plan_b, plan_a = compute_heijunka_plan_counts(state.board, state.board_a, daily_orders, slots_per_day_b=20, slots_per_day_a=26)

    # Snapshot planned board levels for "Fehlend" tracking before execution updates boards.
    state.planned_snapshot_b = _snapshot_from_board(state.board)
    state.planned_snapshot_a = _snapshot_from_board(state.board_a)

    executed_a, shortages_a, consumption_a = _execute_production_schedule(plan_a, fill_levels, bom_df)
    if state.board_a:
        for product, qty in executed_a.items():
            state.board_a.remove_kanban(product, qty)

    preassembly_qty = _ensure_sf3_min_stock(fill_levels, plan_b, slots_per_day=20)
    executed_b, shortages_b, consumption_b = _execute_production_schedule(plan_b, fill_levels, bom_df)
    if state.board:
        for product, qty in executed_b.items():
            state.board.remove_kanban(product, qty)

    save_material_fill_levels(fill_levels)

    combined_consumption: Dict[str, int] = {}
    for comp, qty in consumption_a.items():
        combined_consumption[comp] = combined_consumption.get(comp, 0) + qty
    for comp, qty in consumption_b.items():
        combined_consumption[comp] = combined_consumption.get(comp, 0) + qty

    booked = state.booked_material_consumption
    daily_booked = dict(booked.daily_consumption.get(day, {}))
    for material, qty in combined_consumption.items():
        daily_booked[material] = daily_booked.get(material, 0) + qty
        booked.cumulative_consumption[material] = booked.cumulative_consumption.get(material, 0) + qty
    booked.daily_consumption[day] = daily_booked

    state.daily_production_executed.append(executed_b)
    state.daily_production_executed_a.append(executed_a)
    state.daily_production_shortages.append(shortages_b)
    state.daily_production_shortages_a.append(shortages_a)
    state.production_executed_days.append(day)
    # Cache missing for next-day On-Order (overwrite, no accumulation).
    missing_b = _missing_from_snapshot_and_shortages(
        getattr(state, 'planned_snapshot_b', {}),
        plan_b,
        executed_b,
        shortages_b,
    )
    missing_a = _missing_from_snapshot_and_shortages(
        getattr(state, 'planned_snapshot_a', {}),
        plan_a,
        executed_a,
        shortages_a,
    )
    state.pending_on_order_b = missing_b
    state.pending_on_order_a = missing_a

    save_simulation_state(state)

    message = f'Produktion für Tag {day} gebucht.'
    has_loop_b_output = any((executed_b or {}).values())
    if preassembly_qty > 0 and has_loop_b_output:
        message = f'{message} SF3 vorproduziert: +{preassembly_qty}.'

    return {
        'status': 'ok',
        'message': message,
        'executed_a': executed_a,
        'executed_b': executed_b,
        'shortages_a': shortages_a,
        'shortages_b': shortages_b,
        'consumption': combined_consumption
    }

def simulate_next_day(state: SimulationState) -> Tuple[SimulationState, Dict[str, int], Dict[str, int]]:
    """
    Simuliere den nächsten Tag:
    1. Prüfe eingehende Lieferungen und fülle Bestände auf
    2. Buche aufgeschobenen FG-Demand vom Vortag
    3. Lade vorausberechnete Bestellungen ODER generiere zufällige
    4. Füge Kanbans zum Board hinzu (Verbrauch)
    5. Berechne Materialverbrauch basierend auf BOM (Buchung bei 'Planen & Produzieren')
    6. Berechne Produktionsplan
    7. Produktion wird nicht automatisch angewendet
    8. Speichere Daten

    Rückgabe: (updated_state, daily_orders, production_schedule)
    """
    # Der nächste Tag wäre current_day + 1 (wird am Ende inkrementiert)
    next_day = state.current_day + 1

    # 0) End-of-day Bilanz (Vortag): FG-Nachfrage aus FG-On-Hand bedienen
    #    -> Bestände ändern sich sichtbar erst beim Klick auf "Nächster Tag".
    if state.current_day >= 1 and getattr(state, 'daily_orders_history', None):
        prev_orders = state.daily_orders_history[-1] if state.daily_orders_history else {}
        _apply_fg_sales_coverage_and_log(state.current_day, prev_orders)
    
    # 1. Prüfe eingehende Lieferungen
    process_incoming_deliveries(state.current_day)
    # 2. Buche aufgeschobenen FG-Demand vom Vortag
    apply_pending_fg_demand(state)
    
    # 2. Bestellungen: aus simulated_orders.csv oder (wenn leer) zufällig erzeugen.
    #    Fallback-Generierung wird wie Bestellsimulation geglättet (70% prev + 30% new),
    #    ohne dafür simulated_orders.csv als "Prev" zu verwenden.
    prev_orders_for_smoothing = state.daily_orders_history[-1] if state.daily_orders_history else None
    daily_orders = get_or_generate_orders_for_day(
        next_day,
        prev_orders=prev_orders_for_smoothing,
        apply_smoothing_on_generate=True,
    )
    
    # Speichere Bestellungen
    state.daily_orders_history.append(daily_orders)
    
    # Berechne Materialverbrauch basierend auf BOM (Buchung bei "Planen & Produzieren")
    material_consumption = calculate_material_consumption(daily_orders)
    state.material_consumption.record_day(state.current_day, material_consumption)
    
    # Option A: material_fill_levels werden NICHT automatisch durch Nachfrage reduziert.
    
    # Berechne und speichere Finanzdaten
    financials = calculate_daily_financials_internal(daily_orders)
    state.financial_history.record_day(next_day, financials)
    save_daily_financials_to_csv(next_day, financials)
    
    # Replenishment-Logik (NFP = On-Hand - Demand, On-Order = 0) und Overflow-Boards füllen
    material_zones = load_material_buffer_zones()
    fill_levels = load_or_create_material_fill_levels()

    # Loop B sicherstellen (FG aus material_pufferzonen)
    if state.board is None:
        state.board = OverflowBoard(products=load_fg_buffers_from_material_zones())
    else:
        fg_products = load_fg_buffers_from_material_zones()
        if set(state.board.products.keys()) != set(fg_products.keys()):
            old_counts = {k: len(v) for k, v in state.board.current_kanbans.items()}
            new_board = OverflowBoard(products=fg_products)
            for prod in fg_products.keys():
                new_board.add_kanban(prod, int(old_counts.get(prod, 0)))
            state.board = new_board

        on_order_b = dict(getattr(state, 'pending_on_order_b', {}) or {})
        repl_b, cards_b = _compute_replenishment_cards(
            products=state.board.products,
            board=state.board,
            on_hand=fill_levels,
            demand=daily_orders,
            zones=material_zones,
            on_order=on_order_b,
        )
    for prod, qty in repl_b.items():
        if qty > 0:
            state.board.add_kanban(prod, qty)
    state.planned_snapshot_b = _snapshot_from_board(state.board)

    if not hasattr(state, 'daily_replenishment_history'):
        state.daily_replenishment_history = []
    if not hasattr(state, 'daily_replenishment_cards_history'):
        state.daily_replenishment_cards_history = []
    state.daily_replenishment_history.append(repl_b)
    state.daily_replenishment_cards_history.append(cards_b)

    # Loop A sicherstellen (SF2)
    if state.board_a is None:
        products_a = load_sf2_buffers_from_material_zones()
        state.board_a = OverflowBoard(products=products_a)

    sf2_demand = get_sf2_orders_from_fg_orders(daily_orders)
    on_order_a = dict(getattr(state, 'pending_on_order_a', {}) or {})
    repl_a, cards_a = _compute_replenishment_cards(
        products=state.board_a.products,
        board=state.board_a,
        on_hand=fill_levels,
        demand=sf2_demand,
        zones=material_zones,
        on_order=on_order_a,
    )
    # Reset pending On-Order after it has been applied for the new day.
    state.pending_on_order_b = {}
    state.pending_on_order_a = {}
    for prod, qty in repl_a.items():
        if qty > 0:
            state.board_a.add_kanban(prod, qty)
    state.planned_snapshot_a = _snapshot_from_board(state.board_a)

    if not hasattr(state, 'daily_replenishment_history_a'):
        state.daily_replenishment_history_a = []
    if not hasattr(state, 'daily_replenishment_cards_history_a'):
        state.daily_replenishment_cards_history_a = []
    state.daily_replenishment_history_a.append(repl_a)
    state.daily_replenishment_cards_history_a.append(cards_a)

    # Produktionsplan berechnen (Heijunka), aber nicht automatisch anwenden
    plan_b, plan_a = compute_heijunka_plan_counts(state.board, state.board_a, daily_orders, slots_per_day_b=20, slots_per_day_a=26)
    state.daily_production_history.append(plan_b)
    state.daily_production_history_a.append(plan_a)
    
    # Inkrementiere Tag
    state.current_day += 1

    # Auto-Bestellungen basierend auf aktualisierten Füllständen
    auto_reorder_materials(state.current_day, state)
    
    # Speichere Zustand
    save_simulation_state(state)
    
    return state, daily_orders, plan_b


def jump_to_day(target_day: int) -> Tuple[SimulationState, Dict[str, int], Dict[str, int], str]:
    """
    Springe direkt zu einem bestimmten Tag.

    Prüft ob vorausberechnete Bestellungen für alle Tage bis target_day vorhanden sind.
    Falls nicht: gibt Fehlermeldung zurück.
    Falls ja: simuliert alle Tage bis target_day und bucht Produktion automatisch.

    Args:
        target_day: Zieltag zu dem gesprungen werden soll

    Returns:
        (state, daily_orders, daily_production, error_message)
        error_message ist None bei Erfolg, ansonsten enthält es die Fehlermeldung
    """
    state = load_or_create_simulation_state()
    current_day = state.current_day

    # Prüfe ob wir schon bei oder über dem Zieltag sind
    if target_day <= current_day:
        return state, {}, {}, f"Du bist bereits bei Tag {current_day}. Zieltag {target_day} liegt in der Vergangenheit."

    def _auto_execute_current_day(state_obj: SimulationState) -> None:
        executed_days = set(getattr(state_obj, 'production_executed_days', []) or [])
        if state_obj.current_day <= 0 or state_obj.current_day in executed_days:
            return
        # Mark as planned to keep state consistent with manual flow.
        state_obj.heijunka_planned_day_b = int(state_obj.current_day)
        state_obj.heijunka_planned_day_a = int(state_obj.current_day)
        execute_production_for_today(state_obj)

    # Ensure current day is closed before jumping forward.
    _auto_execute_current_day(state)

    # Simuliere alle Tage von current_day+1 bis target_day
    last_orders = {}
    last_production = {}

    for day in range(current_day + 1, target_day + 1):
        state, last_orders, last_production = simulate_next_day(state)
        _auto_execute_current_day(state)

    return state, last_orders, last_production, None


def _apply_fg_sales_coverage_and_log(day: int, demand: Dict[str, int]) -> None:
    """Bedient FG-Nachfrage aus FG-On-Hand (Fill Levels) und loggt Shipped/Backorder."""
    fg_names = {'CT5', 'CT6', 'CT7', 'TT6', 'TT7', 'TT8'}
    fill_levels = load_or_create_material_fill_levels()

    rows = []
    demand = demand or {}
    for prod in sorted(fg_names):
        d = int(demand.get(prod, 0))
        if d <= 0:
            continue

        on_hand = int(fill_levels.get(prod, 0))
        shipped = min(on_hand, d)
        backorder = max(0, d - shipped)
        fill_levels[prod] = max(0, on_hand - shipped)

        rows.append({
            'Day': int(day),
            'Product': prod,
            'DemandQty': int(d),
            'ShippedQty': int(shipped),
            'BackorderQty': int(backorder),
        })

    save_material_fill_levels(fill_levels)
    _append_sales_log_rows(rows)


def _append_sales_log_rows(rows: List[Dict[str, object]]) -> None:
    """Append rows to outputs/sales_log.csv."""
    output_path = Path(__file__).parent.parent / 'outputs' / 'sales_log.csv'
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df_new = pd.DataFrame(rows or [], columns=['Day', 'Product', 'DemandQty', 'ShippedQty', 'BackorderQty'])
    if output_path.exists():
        try:
            df_old = pd.read_csv(output_path)
            df_all = pd.concat([df_old, df_new], ignore_index=True)
        except Exception:
            df_all = df_new
    else:
        df_all = df_new

    df_all.to_csv(output_path, index=False)


def save_simulation_to_csv(state: SimulationState):
    """
    Speichere komplette Simulationshistorie in CSV-Dateien.
    - daily_orders_log.csv: Bestellungen pro Tag
    - daily_production_log.csv: Produktion pro Tag
    - current_board_state.csv: Aktueller Board-Status
    - material_consumption_log.csv: Materialverbrauch pro Tag
    """
    output_dir = Path(__file__).parent.parent / 'outputs'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Daily Orders Log
    orders_records = []
    for day_idx, orders in enumerate(state.daily_orders_history, 1):
        for product, qty in orders.items():
            orders_records.append({'Day': day_idx, 'Product': product, 'OrderQty': qty})
    
    if orders_records:
        orders_df = pd.DataFrame(orders_records)
        orders_df.to_csv(output_dir / 'daily_orders_log.csv', index=False)
    
    # 2. Daily Production Log
    production_records = []
    for day_idx, schedule in enumerate(state.daily_production_history, 1):
        for product, qty in schedule.items():
            production_records.append({'Day': day_idx, 'Product': product, 'ProducedQty': qty})
    
    if production_records:
        production_df = pd.DataFrame(production_records)
        production_df.to_csv(output_dir / 'daily_production_log.csv', index=False)
    
    # 3. Material Consumption Log
    material_records = []
    for day_idx, consumption in state.material_consumption.daily_consumption.items():
        for material, qty in consumption.items():
            material_records.append({'Day': day_idx, 'Material': material, 'ConsumedQty': qty})
    
    if material_records:
        material_df = pd.DataFrame(material_records)
        material_df.to_csv(output_dir / 'material_consumption_log.csv', index=False)
    
    # 4. Current Board State
    board_dict = state.board.to_dict()
    board_records = []
    for product_name, data in board_dict.items():
        board_records.append({
            'Product': product_name,
            'Current_Total': data['current_total'],
            'Green': data['green_current'],
            'Yellow': data['yellow_current'],
            'Red': data['red_current'],
            'Capacity': data['total_capacity'],
            'Fill_%': data['fill_percentage'] * 100,
            'Zone': data['current_zone'],
            'IsEvent': data['is_event']
        })
    
    board_df = pd.DataFrame(board_records)
    board_df.to_csv(output_dir / 'current_board_state.csv', index=False)


def reset_simulation():
    """
    Setze Simulationszustand zurück auf Tag 1 mit sofortiger Simulation.
    - Bestellungen starten bei Top of Green
    - Tag 1 wird direkt simuliert (Bestellungen generiert, Verbrauch berechnet)
    - Füllstände werden entsprechend reduziert
    - Finanzhistorie wird geleert
    - Alle CSV-Logs werden geleert

    Rückgabe: (state, daily_orders, daily_production)
    """
    import pickle
    from pathlib import Path
    
    state_file = Path(__file__).parent.parent / 'data' / 'simulation_state.pkl'
    
    if state_file.exists():
        # Unter Windows kann die Datei gelockt sein (z.B. durch zweiten Prozess/Reload).
        # Reset darf dann nicht crashen – wir überschreiben den Zustand später regulär.
        try:
            state_file.unlink()
        except PermissionError:
            pass
    
    # Lösche offene Bestellungen
    bestellungen_path = Path(__file__).parent.parent / 'data' / 'bestellungen.csv'
    if bestellungen_path.exists():
        pd.DataFrame(columns=['Bestell_ID', 'Material', 'Menge', 'Bestelltag', 'Liefertag', 'Status']).to_csv(bestellungen_path, index=False)
    
    # Lösche vorausberechnete Bestellsimulation
    simulated_orders_path = Path(__file__).parent.parent / 'data' / 'simulated_orders.csv'
    if simulated_orders_path.exists():
        pd.DataFrame(columns=['Day', 'CT5', 'CT6', 'CT7', 'TT6', 'TT7', 'TT8']).to_csv(simulated_orders_path, index=False)
    
    # Lösche Finanzhistorie CSV
    financials_path = Path(__file__).parent.parent / 'outputs' / 'daily_financials_log.csv'
    if financials_path.exists():
        pd.DataFrame(columns=['Day', 'Revenue', 'Cost', 'Profit', 'Margin', 'Products_Sold']).to_csv(financials_path, index=False)

    # Lösche Sales-Log (Shipments) damit Resets keine Duplikate erzeugen
    sales_log_path = Path(__file__).parent.parent / 'outputs' / 'sales_log.csv'
    if sales_log_path.exists():
        pd.DataFrame(columns=['Day', 'Product', 'DemandQty', 'ShippedQty', 'BackorderQty']).to_csv(sales_log_path, index=False)

    # Lösche Production-Ledger (Materialverbrauch/Produktion) für saubere Neuläufe
    production_ledger_path = Path(__file__).parent.parent / 'outputs' / 'production_ledger.csv'
    if production_ledger_path.exists():
        pd.DataFrame(columns=['day', 'type', 'sku', 'qty', 'for_product']).to_csv(production_ledger_path, index=False)
    
    # Lösche Material-Consumption Log
    consumption_path = Path(__file__).parent.parent / 'outputs' / 'material_consumption_log.csv'
    if consumption_path.exists():
        pd.DataFrame(columns=['Day', 'Material', 'ConsumedQty']).to_csv(consumption_path, index=False)

    # Setze Material-Füllstände auf Top of Green (Red + Yellow + Green = Total)
    material_zones = load_material_buffer_zones()
    fill_levels = {}
    for material, zones in material_zones.items():
        # Top of Green = Red Zone + Yellow Zone + Green Zone = Total Buffer
        fill_levels[material] = zones['total']
    save_material_fill_levels(fill_levels)
    
    # Erstelle neuen Zustand bei Tag 0 (wird dann auf Tag 1 simuliert)
    products = load_fg_buffers_from_material_zones()
    board = OverflowBoard(products=products)
    products_a = load_sf2_buffers_from_material_zones()
    board_a = OverflowBoard(products=products_a)
    state = SimulationState(current_day=0, board=board, board_a=board_a)
    
    # Simuliere sofort Tag 1
    state, daily_orders, daily_production = simulate_next_day(state)
    
    return state, daily_orders, daily_production


# ============================================================================
# BOM (Bill of Materials) Functions - für Materialverbrauch Tracking
# ============================================================================

def load_bom_from_csv() -> pd.DataFrame:
    """
    Lade Bill of Materials (BOM) aus CSV.
    Format: Product, Component, Quantity
    
    Rückgabe: DataFrame mit Produkten und deren benötigten Komponenten
    """
    csv_path = Path(__file__).parent.parent / 'data' / 'raw' / 'bom.csv'
    
    df = pd.read_csv(csv_path)
    return df


def calculate_material_consumption(
    daily_orders: Dict[str, int],
    bom_df: pd.DataFrame = None
) -> Dict[str, int]:
    """
    Berechne Materialverbrauch basierend auf daily_orders und BOM.
    
    Args:
        daily_orders: Dict mit Produkten und bestellten Mengen
        bom_df: BOM DataFrame (wenn None, wird geladen)

    Rückgabe: Dict mit Komponenten und verbrauchten Mengen

    Beispiel:
        daily_orders = {'CT5': 2, 'TT6': 1}
        -> material_consumption = {'Seal_rings': 14, 'Screws': 32, ...}
    """
    
    if bom_df is None:
        bom_df = load_bom_from_csv()
    
    material_consumption = {}
    
    # Für jedes bestellte Produkt
    for product, order_qty in daily_orders.items():
        # Finde BOM-Einträge für dieses Produkt
        product_bom = bom_df[bom_df['Product'] == product]
        
        # Für jede Komponente
        for _, row in product_bom.iterrows():
            component = row['Component']
            qty_per_product = row['Quantity']
            total_qty = order_qty * qty_per_product
            
            if component not in material_consumption:
                material_consumption[component] = 0
            
            material_consumption[component] += total_qty
    
    return material_consumption


def get_sf2_orders_from_fg_orders(daily_orders: Dict[str, int]) -> Dict[str, int]:
    """
    Ableitung der SF2-Nachfrage aus FG-Bestellungen via BOM.
    Nur Antriebswellen werden als SF2-Orders zurueckgegeben.
    """
    if not daily_orders:
        return {}
    consumption = calculate_material_consumption(daily_orders)
    sf2_orders = {}
    for component, qty in consumption.items():
        if str(component).startswith('Antriebswelle') and qty > 0:
            sf2_orders[component] = qty
    return sf2_orders


# ============================================================================
# Financial Calculation Functions - für Finanz-Tracking
# ============================================================================

def load_unit_prices() -> Dict[str, float]:
    """Lade Verkaufspreise der Produkte"""
    try:
        df = pd.read_csv(Path(__file__).parent.parent / 'data' / 'unit_prices.csv')
        return dict(zip(df['product_id'], df['unit_price_eur']))
    except:
        return {
            'CT5': 1000, 'CT6': 1500, 'CT7': 3000,
            'TT6': 14000, 'TT7': 18000, 'TT8': 25000
        }

def get_material_unit_costs() -> Dict[str, float]:
    """Hole Stückkosten pro Material"""
    try:
        df = pd.read_csv(Path(__file__).parent.parent / 'data' / 'material_costs.csv')
        return dict(zip(df['material_name'], df['unit_cost_eur']))
    except:
        return {
            'Wellrohlinge': 45.0, 'Aluminiumblock': 120.0, 'Dichtungsringe': 2.50,
            'Schrauben': 0.15, 'Lager': 35.0, 'Zahnräder': 85.0
        }

def calculate_product_cost(product_id: str) -> float:
    """Berechne Herstellungskosten eines Produkts basierend auf BOM"""
    material_costs = get_material_unit_costs()
    bom_df = load_bom_from_csv()
    
    product_bom = bom_df[bom_df['Product'] == product_id]
    
    total_cost = 0
    for _, row in product_bom.iterrows():
        component = row['Component']
        qty = row['Quantity']
        unit_cost = material_costs.get(component, 0)
        total_cost += unit_cost * qty
    
    return total_cost

def calculate_daily_financials_internal(daily_orders: Dict[str, int]) -> Dict[str, float]:
    """
    Berechne Tagesfinanzen basierend auf Bestellungen/Produktion.
    Interne Version für Server-seitige Berechnung.
    """
    unit_prices = load_unit_prices()
    
    total_revenue = 0
    total_cost = 0
    products_sold = 0
    
    if daily_orders and isinstance(daily_orders, dict):
        for product_id, qty in daily_orders.items():
            if qty > 0:
                # Umsatz
                price = unit_prices.get(product_id, 0)
                total_revenue += price * qty
                
                # Kosten
                cost = calculate_product_cost(product_id)
                total_cost += cost * qty
                
                products_sold += qty
    
    profit = total_revenue - total_cost
    margin = (profit / total_revenue * 100) if total_revenue > 0 else 0
    
    return {
        'revenue': total_revenue,
        'cost': total_cost,
        'profit': profit,
        'margin': margin,
        'products_sold': products_sold
    }

def save_daily_financials_to_csv(day: int, financials: Dict[str, float]):
    """Speichere Finanzdaten in CSV für Persistenz"""
    csv_path = Path(__file__).parent.parent / 'outputs' / 'daily_financials_log.csv'
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Lade existierende Daten oder erstelle neue
    if csv_path.exists():
        df = pd.read_csv(csv_path)
    else:
        df = pd.DataFrame(columns=['Day', 'Revenue', 'Cost', 'Profit', 'Margin', 'Products_Sold'])
    
    # Prüfe ob Tag schon existiert
    if day in df['Day'].values:
        # Update existierenden Tag
        df.loc[df['Day'] == day, ['Revenue', 'Cost', 'Profit', 'Margin', 'Products_Sold']] = [
            financials['revenue'], financials['cost'], financials['profit'], 
            financials['margin'], financials['products_sold']
        ]
    else:
        # Füge neuen Tag hinzu
        new_row = pd.DataFrame([{
            'Day': day,
            'Revenue': financials['revenue'],
            'Cost': financials['cost'],
            'Profit': financials['profit'],
            'Margin': financials['margin'],
            'Products_Sold': financials['products_sold']
        }])
        df = new_row if df.empty else pd.concat([df, new_row], ignore_index=True)
    
    # Sortiere nach Tag und speichere
    df = df.sort_values('Day')
    df.to_csv(csv_path, index=False)


def load_financial_history_from_csv() -> List[Dict[str, float]]:
    """Lade komplette Finanzhistorie aus CSV"""
    csv_path = Path(__file__).parent.parent / 'outputs' / 'daily_financials_log.csv'
    
    if not csv_path.exists():
        return []
    
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return []
        
        df = df.sort_values('Day')
        history = []
        for _, row in df.iterrows():
            history.append({
                'day': int(row['Day']),
                'revenue': float(row['Revenue']),
                'cost': float(row['Cost']),
                'profit': float(row['Profit']),
                'margin': float(row['Margin']),
                'products_sold': int(row['Products_Sold'])
            })
        return history
    except:
        return []


def load_material_buffer_zones() -> Dict[str, Dict[str, int]]:
    """
    Lade Material-Pufferzonen aus material_pufferzonen.csv.
    
    Enthält alle Rohstoffe und Halbfertigprodukte:
    - Wellrohlinge, Aluminiumblock (Rohstoffe)
    - Antriebswellen 5-8 Gang (Halbfertigprodukte)
    - Schrauben, Dichtungsringe, Zahnräder, Lager (Rohstoffe)

    Rückgabe: Dict mit Material-Namen und deren Grün/Gelb/Rot Zonen
    """
    csv_path = Path(__file__).parent.parent / 'data' / 'raw' / 'material_pufferzonen.csv'
    
    try:
        df = pd.read_csv(csv_path)
        
        material_zones = {}
        
        for _, row in df.iterrows():
            material_name = row['Material']
            green = int(float(row['Green Zone [pcs]']))
            yellow = int(float(row['Yellow Zone [pcs]']))
            red = int(float(row['Total Red Zone [pcs]']))
            
            material_zones[material_name] = {
                'green': green,
                'yellow': yellow,
                'red': red,
                'total': green + yellow + red
            }
        
        return material_zones
    except Exception as e:
        print(f" Fehler beim Laden der Pufferzonen aus material_pufferzonen.csv: {e}")
        return {}


# ============================================================================
# Einkauf / Bestellungen (Auto-Reorder)
# ============================================================================

# Gemeinsame Reorder-Regeln (s, q): Standard-Regeln (legacy s/q)
AUTO_RULES = {
    "Dichtungsringe": {"s": 889, "q": 7494},
    "Schrauben": {"s": 1988, "q": 14020},
}

def load_toy_rules_from_csv():
    """
    Lade Reorder-Punkte (ToY) aus pufferzonen.csv.
    ToY = Yellow Zone + Total Red Zone; Bestellmenge = Green + Yellow + Total Red (gesamter Puffer).
    """
    toy_path = Path(__file__).parent.parent / 'data' / 'raw' / 'pufferzonen.csv'
    toy_fallback_path = Path(__file__).parent.parent / 'data' / 'raw' / 'material_pufferzonen.csv'
    rules = {}
    try:
        df = pd.read_csv(toy_path, index_col=0)
        item_row = df.loc['Item']
        toy_row = df.loc['ToY (Reorder point)']
        total_row = df.loc['Total Buffer [pcs]']

        name_map = {
            'Wellenrohling': 'Wellrohlinge',
            'Aluminiumblock': 'Aluminiumblock',
            'Zahnräder': 'Zahnräder',
            'Lager': 'Lager'
        }
        allowed = set(name_map.values())

        for col in df.columns:
            material_raw = str(item_row.get(col, '')).strip()
            if not material_raw:
                continue
            material = name_map.get(material_raw, material_raw)
            if material not in allowed:
                continue

            reorder_point = pd.to_numeric(toy_row.get(col), errors='coerce')
            qty = pd.to_numeric(total_row.get(col), errors='coerce')
            if pd.isna(reorder_point) or pd.isna(qty):
                continue

            rules[material] = {"s": int(reorder_point), "q": int(qty)}
    except Exception:
        pass

    # Fallback: Falls Materialien nur in material_pufferzonen.csv stehen
    try:
        df_fallback = pd.read_csv(toy_fallback_path)
        for _, row in df_fallback.iterrows():
            material = str(row['Material']).strip()
            if material not in {'Wellrohlinge', 'Aluminiumblock', 'Zahnräder', 'Lager'}:
                continue
            if material in rules:
                continue
            green = pd.to_numeric(row.get('Green Zone [pcs]'), errors='coerce')
            yellow = pd.to_numeric(row.get('Yellow Zone [pcs]'), errors='coerce')
            red = pd.to_numeric(row.get('Total Red Zone [pcs]'), errors='coerce')
            if pd.isna(green) or pd.isna(yellow) or pd.isna(red):
                continue
            reorder_point = yellow + red
            qty = green + yellow + red
            rules[material] = {"s": int(reorder_point), "q": int(qty)}
    except Exception:
        pass

    return rules

def _load_simulated_orders_df() -> pd.DataFrame:
    """Lade simulated_orders.csv für Forecast-Berechnungen."""
    csv_path = Path(__file__).parent.parent / 'data' / 'simulated_orders.csv'
    try:
        df = pd.read_csv(csv_path)
        return df
    except Exception:
        return pd.DataFrame(columns=['Day'])

def _load_fg_daily_forecast_int() -> Dict[str, int]:
    """Lade Forecast je FG-Produkt (int pro Tag) aus Demand_Simulation.csv."""
    means = _load_fg_daily_demand_means()
    forecast = {}
    for product, mean in means.items():
        try:
            forecast[product] = int(round(float(mean)))
        except Exception:
            forecast[product] = 0
    return forecast

def _daily_orders_from_forecast(day: int, orders_df: pd.DataFrame, fallback_forecast: dict) -> dict:
    """Return daily orders from simulated_orders.csv or fallback forecast."""
    if orders_df is not None and not orders_df.empty and 'Day' in orders_df.columns:
        match = orders_df[orders_df['Day'] == day]
        if not match.empty:
            row = match.iloc[0]
            orders = {}
            for col in orders_df.columns:
                if col == 'Day':
                    continue
                val = row.get(col)
                if pd.isna(val):
                    continue
                orders[col] = int(val)
            return orders
    return dict(fallback_forecast) if fallback_forecast else {}

def load_recent_capacity_daily_material_consumption(
    days: int = 5,
    bom_df: pd.DataFrame = None,
    state: SimulationState = None
) -> dict:
    """
    Schätze tägliche Materialnachfrage basierend auf tatsächlicher Produktion.
    Fallback: geplante Produktion, falls keine Ist-Daten vorliegen.
    """
    state = state or load_or_create_simulation_state()
    history = []

    executed = getattr(state, 'daily_production_executed', []) or []
    for day in reversed(executed):
        if day and any(int(v) for v in day.values()):
            history.append(day)
        if len(history) >= days:
            break

    if not history:
        planned = getattr(state, 'daily_production_history', []) or []
        for day in reversed(planned):
            if day and any(int(v) for v in day.values()):
                history.append(day)
            if len(history) >= days:
                break

    if not history:
        return {}

    totals = {}
    for day in history:
        for product, qty in day.items():
            totals[product] = totals.get(product, 0) + int(qty)

    avg_products = {product: int(round(qty / len(history))) for product, qty in totals.items()}
    if not any(avg_products.values()):
        return {}

    bom_df = bom_df if bom_df is not None else load_bom_from_csv()
    return calculate_material_consumption(avg_products, bom_df)

def calculate_expected_material_demand(
    material: str,
    current_day: int,
    lead_time_days: int,
    orders_df: pd.DataFrame = None,
    fallback_forecast: dict = None,
    bom_df: pd.DataFrame = None,
    capacity_daily: dict = None
) -> int:
    """
    Erwartete Nachfrage bis Lieferung aus realen/forecasted Orders.
    Berechnung basiert auf Bestellungen (simulated_orders.csv) plus BOM.
    """
    lead_time_days = max(int(lead_time_days or 0), 0)
    if lead_time_days <= 0:
        return 0

    orders_df = orders_df if orders_df is not None else _load_simulated_orders_df()
    fallback_forecast = fallback_forecast if fallback_forecast is not None else _load_fg_daily_forecast_int()
    bom_df = bom_df if bom_df is not None else load_bom_from_csv()
    capacity_daily = capacity_daily or {}

    expected = 0
    for day in range(current_day + 1, current_day + lead_time_days + 1):
        daily_orders = _daily_orders_from_forecast(day, orders_df, fallback_forecast)
        if not daily_orders:
            continue
        consumption = calculate_material_consumption(daily_orders, bom_df)
        daily_need = int(consumption.get(material, 0))
        cap = capacity_daily.get(material)
        if cap is not None and cap > 0:
            expected += min(daily_need, int(cap))
        else:
            expected += daily_need
    return expected

def load_lieferzeiten():
    """Lade Lieferzeiten aus CSV"""
    csv_path = Path(__file__).parent.parent / 'data' / 'raw' / 'lieferzeiten.csv'
    try:
        df = pd.read_csv(csv_path)
        return df.set_index('Material').to_dict('index')
    except:
        return {}

def load_bestellungen():
    """Lade offene Bestellungen aus CSV"""
    csv_path = Path(__file__).parent.parent / 'data' / 'bestellungen.csv'
    try:
        df = pd.read_csv(csv_path)
        return df
    except:
        return pd.DataFrame(columns=['Bestell_ID', 'Material', 'Menge', 'Bestelltag', 'Liefertag', 'Status'])

def save_bestellungen(df):
    """Speichere Bestellungen in CSV"""
    csv_path = Path(__file__).parent.parent / 'data' / 'bestellungen.csv'
    df.to_csv(csv_path, index=False)

def add_bestellung(material: str, menge: int, current_day: int):
    """F?ge neue Bestellung hinzu"""
    lieferzeiten = load_lieferzeiten()
    df = load_bestellungen()

    lieferzeit = lieferzeiten.get(material, {}).get('Lieferzeit_Tage', 5)
    liefertag = current_day + lieferzeit

    new_order = {
        'Bestell_ID': str(uuid.uuid4())[:8],
        'Material': material,
        'Menge': menge,
        'Bestelltag': current_day,
        'Liefertag': liefertag,
        'Status': 'offen'
    }

    df = pd.concat([df, pd.DataFrame([new_order])], ignore_index=True)
    save_bestellungen(df)
    return df

def auto_reorder_materials(current_day: int, state: SimulationState = None) -> list:
    """
    Reorder-Regeln (s, q): Wenn Bestand <= s, bestelle q, sofern noch keine offene Bestellung existiert.
    """
    fill_levels = load_or_create_material_fill_levels()
    lieferzeiten = load_lieferzeiten()
    bestellungen = load_bestellungen()
    offene_materialien = set(bestellungen[bestellungen['Status'] == 'offen']['Material']) if not bestellungen.empty else set()

    orders_df = _load_simulated_orders_df()
    fallback_forecast = _load_fg_daily_forecast_int()
    bom_df = load_bom_from_csv()
    capacity_daily = load_recent_capacity_daily_material_consumption(days=5, bom_df=bom_df, state=state)

    created = []
    for material, cfg in AUTO_RULES.items():
        current_level = fill_levels.get(material, 0)
        if current_level <= cfg['s'] and material not in offene_materialien:
            add_bestellung(material, cfg['q'], current_day)
            created.append(material)

    toy_rules = load_toy_rules_from_csv()
    for material, cfg in toy_rules.items():
        current_level = fill_levels.get(material, 0)
        if material in offene_materialien:
            continue
        if current_level > cfg['s']:
            continue

        lead_time = lieferzeiten.get(material, {}).get('Lieferzeit_Tage', 5)
        expected_demand = calculate_expected_material_demand(
            material=material,
            current_day=current_day,
            lead_time_days=lead_time,
            orders_df=orders_df,
            fallback_forecast=fallback_forecast,
            bom_df=bom_df,
            capacity_daily=capacity_daily
        )

        window_end = current_day + max(int(lead_time or 0), 0)
        offene = pd.DataFrame()
        if not bestellungen.empty:
            offene = bestellungen[
                (bestellungen['Material'] == material) &
                (bestellungen['Status'] == 'offen') &
                (bestellungen['Liefertag'] <= window_end)
            ]
        open_supply = offene['Menge'].sum() if not offene.empty else 0

        nfp = current_level + open_supply - expected_demand
        order_qty = max(0, cfg['q'] - nfp)

        min_qty = lieferzeiten.get(material, {}).get('Mindestbestellmenge', 0)
        if min_qty:
            order_qty = max(order_qty, int(min_qty))

        if order_qty > 0:
            add_bestellung(material, int(order_qty), current_day)
            created.append(material)

    return created

# ============================================================================
# Material Fill Level Tracking - persistiert in CSV
# ============================================================================

def load_or_create_material_fill_levels() -> Dict[str, int]:
    """
    Lade Material-Füllstände aus CSV oder erstelle neu.
    Initial: Alle Materialien starten bei Green Zone Level
    """
    csv_path = Path(__file__).parent.parent / 'data' / 'material_fill_levels.csv'
    
    if csv_path.exists():
        df = pd.read_csv(csv_path, index_col='Material')
        return df['Fill_Level'].to_dict()
    else:
        # Erstelle neue Füllstände - starte mit Green Zone
        material_zones = load_material_buffer_zones()
        fill_levels = {}
        
        for material, zones in material_zones.items():
            # Initialisiere mit Green Zone Level (am Anfang)
            fill_levels[material] = zones['green']
        
        save_material_fill_levels(fill_levels)
        return fill_levels


def save_material_fill_levels(fill_levels: Dict[str, int]):
    """Speichere Material-Füllstände in CSV"""
    csv_path = Path(__file__).parent.parent / 'data' / 'material_fill_levels.csv'
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    
    data = {'Material': list(fill_levels.keys()), 'Fill_Level': list(fill_levels.values())}
    df = pd.DataFrame(data)
    df.to_csv(csv_path, index=False)


def process_incoming_deliveries(current_day: int):
    """
    Prüfe und verarbeite eingehende Lieferungen für den aktuellen Tag.
    Bestellungen mit Liefertag == current_day werden dem Bestand hinzugefügt.
    """
    csv_path = Path(__file__).parent.parent / 'data' / 'bestellungen.csv'
    
    try:
        df = pd.read_csv(csv_path)
    except:
        return  # Keine Bestellungen vorhanden
    
    if df.empty:
        return
    
    # Finde Bestellungen die heute geliefert werden
    deliveries_today = df[(df['Liefertag'] == current_day) & (df['Status'] == 'offen')]
    
    if deliveries_today.empty:
        return
    
    # Lade aktuelle Füllstände
    fill_levels = load_or_create_material_fill_levels()
    
    for _, delivery in deliveries_today.iterrows():
        material = delivery['Material']
        menge = int(delivery['Menge'])

        # Füge Menge zum Bestand hinzu
        if material in fill_levels:
            fill_levels[material] += menge
        else:
            fill_levels[material] = menge

        print(f" Lieferung eingegangen: {menge} x {material}")

    # Speichere aktualisierte Füllstände
    save_material_fill_levels(fill_levels)
    
    # Markiere Bestellungen als geliefert
    df.loc[(df['Liefertag'] == current_day) & (df['Status'] == 'offen'), 'Status'] = 'geliefert'
    df.to_csv(csv_path, index=False)


def update_material_fill_levels(consumption: Dict[str, int]):
    """
    Aktualisiere Füllstände durch Verbrauch.
    Jeder Verbrauch reduziert den Füllstand.
    """
    fill_levels = load_or_create_material_fill_levels()
    
    for material, consumed_qty in consumption.items():
        if material in fill_levels:
            fill_levels[material] = max(0, fill_levels[material] - consumed_qty)
    
    save_material_fill_levels(fill_levels)
    return fill_levels


def get_material_fill_percentage(material: str, fill_level: int) -> float:
    """
    Berechne Füllgrad-Prozentsatz eines Materials.
    """
    material_zones = load_material_buffer_zones()
    
    if material not in material_zones:
        return 0.0
    
    total_capacity = material_zones[material]['total']
    
    if total_capacity == 0:
        return 0.0
    
    return min(1.0, fill_level / total_capacity)


def get_material_zone(material: str, fill_level: int) -> str:
    """
    Bestimme Pufferzone für ein Material basierend auf Füllstand.
    
    DDMRP Zonen (von unten nach oben im Balken):
    - Red (unten): 0 bis red_zone -> KRITISCH, muss bestellen
    - Yellow (mitte): red_zone bis (red + yellow) -> Achtung
    - Green (oben): über (red + yellow) -> OK, gut gefüllt

    Beispiel Wellrohlinge: red=214, yellow=475, green=143, total=832
    - 0-214: RED
    - 214-689: YELLOW  
    - 689-832: GREEN
    """
    material_zones = load_material_buffer_zones()
    
    if material not in material_zones:
        return 'GREEN'
    
    zones = material_zones[material]
    red_threshold = zones['red']  # Ende der roten Zone
    yellow_threshold = red_threshold + zones['yellow']  # Ende der gelben Zone
    
    if fill_level <= red_threshold:
        return 'RED'
    elif fill_level <= yellow_threshold:
        return 'YELLOW'
    else:
        return 'GREEN'


# ============================================================================
# Global Material Consumption Calculation (für alle Sparten nutzbar)
# ============================================================================

def get_daily_material_consumption(daily_orders: Dict[str, int]) -> Dict[str, int]:
    """
    Berechne täglichen Materialverbrauch basierend auf Bestellungen und BOM.
    
    Diese Funktion wird global von allen Sparten (Dashboard, DDMRP, etc.) genutzt
    um konsistente Materialverbrauch-Zahlen zu haben.
    
    Args:
        daily_orders: Dict mit Produkt-Namen und Bestellmenge
    
    Returns:
        Dict mit Material-Namen und Verbrauchsmenge
    """
    return calculate_material_consumption(daily_orders)


# ============================================================================
# Example Usage / Test
# ============================================================================

if __name__ == "__main__":
    print("=" * 90)
    print("OVERFLOW-BOARD SIMULATOR - Kanban-Verwaltung nach Heijunka/DDMRP")
    print("=" * 90)
    
    # Lade Simulation
    products = load_Simulation_from_csv()
    print(f"🔬 {len(products)} Produkte geladen aus Demand_Simulation.csv")
    
    # Erstelle Overflow-Board
    board = OverflowBoard(products=products)
    print("Overflow-Board initialisiert")
    
    # Simuliere 3 Tage
    print("\n" + "=" * 90)
    print("TAGES-SIMULATION (3 Tage)")
    print("=" * 90)
    
    for day in range(1, 4):
        print(f"\n{'='*90}")
        print(f"TAG {day}")
        print(f"{'='*90}")
        
        # Simuliere tägliche Bestellungen (zufällig basierend auf ADU)
        daily_orders = {}
        for prod_name, buffer in products.items():
            # Zufällige Bestellmenge um die durchschnittliche tägliche Nutzung
            daily_qty = int(np.random.poisson(buffer.daily_usage))
            if daily_qty > 0:
                daily_orders[prod_name] = daily_qty
        
        print(f"\n Lieferung eingegangen: {menge} x {material}")
        for prod, qty in sorted(daily_orders.items()):
            print(f"   {prod:10} -> {qty:3d} Stück")
        
        # Kanbans ins Overflow-Board
        board = simulate_daily_consumption(board, daily_orders)
        
        # Zeige Overflow-Board Status
        print(f"\n Overflow-Board Status nach Verbrauch:")
        print(f"{'Produkt':15} | {'Aktuell':8} | {'Max':8} | {'%Füll':6} | {'Zone':8} | {'Event':5} | {'Priority'}")
        print("-" * 90)
        
        ranking = board.get_priority_ranking()
        for i, (prod_name, fill_pct, zone) in enumerate(ranking, 1):
            current = len(board.current_kanbans.get(prod_name, []))
            max_kanbans = board.products[prod_name].get_max_kanbans()
            is_event = "E" if board.products[prod_name].is_event_kanban else ""
            priority_mark = "*" * min(i, 3) if i <= 3 else ""
            print(f"{prod_name:15} | {current:8d} | {max_kanbans:8d} | {fill_pct*100:5.1f}% | {zone.value:8} | {is_event:5} | {priority_mark}")
        
        # Berechne & wende Produktionsplan an
        schedule = calculate_production_schedule(board, pitch_minutes=30, takt_time_seconds=300)
        print(f"\n[Plan] Produktionsplan (Pitch 30 Min, Takt 300s):")
        if schedule:
            for prod_name, units in schedule.items():
                print(f"   {prod_name:15} -> {units:3d} Kanbans produzieren")
        else:
            print("   (Keine Produktion erforderlich - Board leer)")
        
        board = apply_production_schedule(board, schedule)
        print(f"\n[OK] Produktion durchgefuehrt")
    
    print("\n" + "=" * 90)
    print("SIMULATION ABGESCHLOSSEN")
    print("=" * 90)



