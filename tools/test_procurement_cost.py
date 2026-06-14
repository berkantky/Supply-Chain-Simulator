"""Quick verification for procurement cost logic.

What it checks:
- Pure function behavior: sums qty * unit_cost and counts order_cost once per Bestell_ID.
- If data/bestellungen.csv has rows, compares the pure function result against
  components.layout_finanzen.procurement_cost_for_day(day).

Run:
  python tools/test_procurement_cost.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import pandas as pd


@dataclass(frozen=True)
class MaterialParams:
    unit_cost_eur: float
    order_cost_eur: float


def compute_procurement_cost_for_day(df_orders: pd.DataFrame, params: dict[str, MaterialParams], day: int) -> float:
    day = int(day or 0)
    if day <= 0 or df_orders is None or df_orders.empty:
        return 0.0

    if not {"Bestelltag", "Material", "Menge"}.issubset(df_orders.columns):
        return 0.0

    df_day = df_orders.copy()
    df_day["Bestelltag"] = pd.to_numeric(df_day["Bestelltag"], errors="coerce").fillna(0).astype(int)
    df_day = df_day[df_day["Bestelltag"] == day]
    if df_day.empty:
        return 0.0

    df_day["Material"] = df_day["Material"].fillna("").astype(str)
    df_day["Menge"] = pd.to_numeric(df_day["Menge"], errors="coerce").fillna(0).astype(int)

    total = 0.0
    if "Bestell_ID" in df_day.columns and df_day["Bestell_ID"].fillna("").astype(str).str.strip().ne("").any():
        df_day["Bestell_ID"] = df_day["Bestell_ID"].fillna("").astype(str).str.strip()
        for order_id, grp in df_day.groupby("Bestell_ID"):
            if not order_id:
                continue

            # variable costs
            for _, row in grp.iterrows():
                mat = str(row.get("Material", "")).strip()
                qty = int(row.get("Menge", 0) or 0)
                p = params.get(mat, MaterialParams(0.0, 0.0))
                total += float(qty) * float(p.unit_cost_eur)

            # fixed order cost (matching app logic: first row's material)
            mat0 = str(grp.iloc[0].get("Material", "")).strip()
            p0 = params.get(mat0, MaterialParams(0.0, 0.0))
            total += float(p0.order_cost_eur)
    else:
        for _, row in df_day.iterrows():
            mat = str(row.get("Material", "")).strip()
            qty = int(row.get("Menge", 0) or 0)
            p = params.get(mat, MaterialParams(0.0, 0.0))
            total += float(qty) * float(p.unit_cost_eur) + float(p.order_cost_eur)

    return float(total)


def load_params_from_material_costs(csv_path: Path) -> dict[str, MaterialParams]:
    df = pd.read_csv(csv_path)
    out: dict[str, MaterialParams] = {}
    for _, row in df.iterrows():
        name = str(row.get("material_name", "")).strip()
        if not name:
            continue
        unit_cost = float(pd.to_numeric(row.get("unit_cost_eur", 0), errors="coerce") or 0.0)
        order_cost = float(pd.to_numeric(row.get("order_cost_eur", 0), errors="coerce") or 0.0)
        out[name] = MaterialParams(unit_cost_eur=unit_cost, order_cost_eur=order_cost)
    return out


def _assert_in_memory_example() -> None:
    params = {
        "Wellrohlinge": MaterialParams(unit_cost_eur=45.0, order_cost_eur=150.0),
        "Aluminiumblock": MaterialParams(unit_cost_eur=120.0, order_cost_eur=200.0),
    }
    df = pd.DataFrame(
        [
            {"Bestell_ID": "A", "Material": "Wellrohlinge", "Menge": 10, "Bestelltag": 3},
            {"Bestell_ID": "A", "Material": "Aluminiumblock", "Menge": 2, "Bestelltag": 3},
            {"Bestell_ID": "B", "Material": "Wellrohlinge", "Menge": 1, "Bestelltag": 3},
        ]
    )

    # Expected: A => 10*45 + 2*120 + order_cost(first material in A = Wellrohlinge = 150)
    #           B => 1*45 + order_cost(first material in B = Wellrohlinge = 150)
    expected = (10 * 45.0 + 2 * 120.0 + 150.0) + (1 * 45.0 + 150.0)
    got = compute_procurement_cost_for_day(df, params, 3)
    assert abs(got - expected) < 1e-9, (got, expected)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    material_costs = repo_root / "data" / "material_costs.csv"
    bestellungen = repo_root / "data" / "bestellungen.csv"

    print("[1] In-memory example…")
    _assert_in_memory_example()
    print("OK")

    print("\n[2] Real-file comparison…")
    if not material_costs.exists():
        print("Missing:", material_costs)
        return

    params = load_params_from_material_costs(material_costs)
    if not bestellungen.exists():
        print("Missing:", bestellungen)
        return

    df_orders = pd.read_csv(bestellungen)
    if df_orders.empty:
        print("bestellungen.csv is empty -> procurement cost is 0 (expected).")
        return

    from components.layout_finanzen import procurement_cost_for_day

    df_orders["Bestelltag"] = pd.to_numeric(df_orders.get("Bestelltag", 0), errors="coerce").fillna(0).astype(int)
    days = sorted(int(d) for d in df_orders["Bestelltag"].unique() if int(d) > 0)
    for d in days:
        pure = compute_procurement_cost_for_day(df_orders, params, d)
        app = float(procurement_cost_for_day(d) or 0.0)
        delta = pure - app
        print(f"Day {d}: pure={pure:.2f}€, app={app:.2f}€, delta={delta:.6f}")


if __name__ == "__main__":
    main()
