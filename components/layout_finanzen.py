"""
components/layout_finanzen.py

Finanz-Dashboard mit:
- KPI-Kacheln für Umsatz, Kosten, Gewinn (Tages- UND Gesamt-KPIs)
- Tägliche Produktions/Verkaufszahlen
- Gewinn/Kosten-Entwicklung über Zeit
- Dynamische Kostenberechnung basierend auf Materialverbrauch
- Server-seitige Finanzhistorie für konsistente Daten beim Springen
"""

from pathlib import Path

import pandas as pd
from dash import html, dcc, callback, Input, Output, State
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ============================================================================
# Daten laden
# ============================================================================

def load_unit_prices():
    """Lade Verkaufspreise der Produkte"""
    try:
        df = pd.read_csv('data/unit_prices.csv')
        return dict(zip(df['product_id'], df['unit_price_eur']))
    except:
        return {
            'CT5': 1000, 'CT6': 1500, 'CT7': 3000,
            'TT6': 14000, 'TT7': 18000, 'TT8': 25000
        }

def load_material_costs():
    """Lade Materialkosten"""
    try:
        df = pd.read_csv('data/material_costs.csv')
        return df.to_dict('records')
    except:
        return []

def get_material_unit_costs():
    """Hole Stückkosten pro Material"""
    try:
        df = pd.read_csv('data/material_costs.csv')
        return dict(zip(df['material_name'], df['unit_cost_eur']))
    except:
        return {
            'Wellrohlinge': 45.0, 'Aluminiumblock': 120.0, 'Dichtungsringe': 2.50,
            'Schrauben': 0.15, 'Lager': 35.0, 'Zahnräder': 85.0
        }


def get_material_procurement_cost_params():
    """Return dict material_name -> {unit_cost_eur, order_cost_eur}."""
    try:
        df = pd.read_csv('data/material_costs.csv')
        params = {}
        for _, row in df.iterrows():
            name = str(row.get('material_name', '')).strip()
            if not name:
                continue
            unit_cost = float(pd.to_numeric(row.get('unit_cost_eur', 0), errors='coerce') or 0.0)
            order_cost = float(pd.to_numeric(row.get('order_cost_eur', 0), errors='coerce') or 0.0)
            params[name] = {'unit_cost_eur': unit_cost, 'order_cost_eur': order_cost}
        return params
    except Exception:
        return {}

def load_bom():
    """Lade BOM aus CSV"""
    try:
        df = pd.read_csv('data/raw/bom.csv')
        bom = {}
        for product in df['Product'].unique():
            product_rows = df[df['Product'] == product]
            bom[product] = dict(zip(product_rows['Component'], product_rows['Quantity']))
        return bom
    except:
        return {}

def calculate_product_cost(product_id):
    """Berechne Herstellungskosten eines Produkts basierend auf BOM"""
    material_costs = get_material_unit_costs()
    bom = load_bom()
    product_bom = bom.get(product_id, {})
    
    total_cost = 0
    for component, qty in product_bom.items():
        unit_cost = material_costs.get(component, 0)
        total_cost += unit_cost * qty
    
    return total_cost

def calculate_daily_financials(daily_orders):
    """Berechne Tagesfinanzen basierend auf Bestellungen/Produktion"""
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


# ============================================================================
# Neue Finanzlogik (Make-to-Stock): Umsatz aus echten Shipments, Kosten aus realem Verbrauch
# ============================================================================

def _read_optional_csv(path: Path) -> pd.DataFrame:
    try:
        if path.exists():
            return pd.read_csv(path)
    except Exception:
        pass
    return pd.DataFrame()


def load_sales_log() -> pd.DataFrame:
    """Load shipped/backorder log (written on 'Nächster Tag')."""
    path = Path(__file__).parent.parent / 'outputs' / 'sales_log.csv'
    df = _read_optional_csv(path)
    if df.empty:
        return df
    # Normalize
    if 'Day' in df.columns:
        df['Day'] = pd.to_numeric(df['Day'], errors='coerce').fillna(0).astype(int)
    for col in ['DemandQty', 'ShippedQty', 'BackorderQty']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)
    if 'Product' in df.columns:
        df['Product'] = df['Product'].astype(str)
    return df


def load_production_ledger() -> pd.DataFrame:
    """Load production ledger (written when clicking 'Produzieren')."""
    path = Path(__file__).parent.parent / 'outputs' / 'production_ledger.csv'
    df = _read_optional_csv(path)
    if df.empty:
        return df
    if 'day' in df.columns:
        df['day'] = pd.to_numeric(df['day'], errors='coerce').fillna(0).astype(int)
    if 'qty' in df.columns:
        df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0).astype(float)
    for col in ['type', 'sku', 'for_product']:
        if col in df.columns:
            df[col] = df[col].fillna('').astype(str)
    return df


def load_bestellungen() -> pd.DataFrame:
    """Load purchase orders created in Einkauf/DDMRP (data/bestellungen.csv)."""
    path = Path(__file__).parent.parent / 'data' / 'bestellungen.csv'
    df = _read_optional_csv(path)
    if df.empty:
        return df
    for col in ['Bestelltag', 'Liefertag', 'Menge']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    if 'Material' in df.columns:
        df['Material'] = df['Material'].fillna('').astype(str)
    if 'Status' in df.columns:
        df['Status'] = df['Status'].fillna('').astype(str)
    if 'Bestell_ID' in df.columns:
        df['Bestell_ID'] = df['Bestell_ID'].fillna('').astype(str)
    return df


def _load_simulation_state_snapshot():
    """Load persisted SimulationState without mutating it.

    Fallback source for finance when ledger CSVs are missing/empty.
    """
    try:
        import pickle

        path = Path(__file__).parent.parent / 'data' / 'simulation_state.pkl'
        if not path.exists():
            return None
        with open(path, 'rb') as f:
            return pickle.load(f)
    except Exception:
        return None


def _executed_qty_from_state_for_day(day: int) -> int:
    """Total executed production qty (Loop A + Loop B) for a given day."""
    day = int(day or 0)
    if day <= 0:
        return 0

    state = _load_simulation_state_snapshot()
    if state is None:
        return 0

    days = list(getattr(state, 'production_executed_days', []) or [])
    if not days:
        return 0

    idx = None
    for i, d in enumerate(days):
        if int(d) == day:
            idx = i
    if idx is None:
        return 0

    executed_b_list = list(getattr(state, 'daily_production_executed', []) or [])
    executed_a_list = list(getattr(state, 'daily_production_executed_a', []) or [])
    executed_b = executed_b_list[idx] if idx < len(executed_b_list) else {}
    executed_a = executed_a_list[idx] if idx < len(executed_a_list) else {}

    total = 0
    for qty in (executed_b or {}).values():
        total += int(qty or 0)
    for qty in (executed_a or {}).values():
        total += int(qty or 0)
    return int(total)


def _material_cost_from_state_for_day(day: int) -> float:
    """Material consumption cost for a day from saved state (booked_material_consumption)."""
    day = int(day or 0)
    if day <= 0:
        return 0.0

    state = _load_simulation_state_snapshot()
    if state is None:
        return 0.0

    booked = getattr(state, 'booked_material_consumption', None)
    daily = getattr(booked, 'daily_consumption', {}) if booked is not None else {}
    consumption = dict(daily.get(day, {}) or {})
    if not consumption:
        return 0.0

    unit_costs = get_material_unit_costs()
    total = 0.0
    for material, qty in consumption.items():
        unit_cost = float(unit_costs.get(str(material).strip(), 0.0) or 0.0)
        total += float(qty or 0) * unit_cost
    return float(total or 0.0)


def _sales_shipped_by_day(df_sales: pd.DataFrame) -> pd.DataFrame:
    if df_sales is None or df_sales.empty:
        return pd.DataFrame(columns=['Day', 'Product', 'ShippedQty'])
    if not {'Day', 'Product', 'ShippedQty'}.issubset(df_sales.columns):
        return pd.DataFrame(columns=['Day', 'Product', 'ShippedQty'])
    # sales_log.csv can contain multiple runs (no run_id). We want the *latest* entry per Day+Product.
    # Within one run, there should be one row per product/day.
    df = df_sales.reset_index().rename(columns={'index': '_row'})
    df = df.sort_values('_row')
    last = df.groupby(['Day', 'Product'], as_index=False).tail(1)
    return last[['Day', 'Product', 'ShippedQty']]


def _sales_last_by_day_product(df_sales: pd.DataFrame) -> pd.DataFrame:
    """Latest sales log rows per Day+Product including demand+ship for service level."""
    if df_sales is None or df_sales.empty:
        return pd.DataFrame(columns=['Day', 'Product', 'DemandQty', 'ShippedQty'])
    required = {'Day', 'Product', 'DemandQty', 'ShippedQty'}
    if not required.issubset(df_sales.columns):
        return pd.DataFrame(columns=['Day', 'Product', 'DemandQty', 'ShippedQty'])
    df = df_sales.reset_index().rename(columns={'index': '_row'})
    df = df.sort_values('_row')
    last = df.groupby(['Day', 'Product'], as_index=False).tail(1)
    return last[['Day', 'Product', 'DemandQty', 'ShippedQty']]


def service_level_for_day(day: int) -> float:
    """Service level (fill rate) for a day: shipped/demand in %."""
    day = int(day or 0)
    if day <= 0:
        return 0.0
    df_sales = load_sales_log()
    df = _sales_last_by_day_product(df_sales)
    if df.empty:
        return 0.0
    df_day = df[df['Day'] == day]
    if df_day.empty:
        return 0.0
    demand = float(df_day['DemandQty'].sum() or 0.0)
    shipped = float(df_day['ShippedQty'].sum() or 0.0)
    if demand <= 0:
        return 0.0
    return float(shipped / demand * 100.0)


def service_level_up_to_day(max_day: int) -> float:
    """Cumulative service level 1..max_day."""
    max_day = int(max_day or 0)
    if max_day <= 0:
        return 0.0
    df_sales = load_sales_log()
    df = _sales_last_by_day_product(df_sales)
    if df.empty:
        return 0.0
    df = df[(df['Day'] >= 1) & (df['Day'] <= max_day)]
    if df.empty:
        return 0.0
    demand = float(df['DemandQty'].sum() or 0.0)
    shipped = float(df['ShippedQty'].sum() or 0.0)
    if demand <= 0:
        return 0.0
    return float(shipped / demand * 100.0)


def shipped_quantities_for_day(day: int) -> dict:
    if day <= 0:
        return {}
    df_sales = load_sales_log()
    df_ship = _sales_shipped_by_day(df_sales)
    if df_ship.empty:
        return {}
    df_day = df_ship[df_ship['Day'] == int(day)]
    shipped = {}
    for _, row in df_day.iterrows():
        qty = float(row.get('ShippedQty', 0) or 0)
        if qty > 0:
            shipped[str(row.get('Product', '')).strip()] = int(round(qty))
    return shipped


def shipped_quantities_up_to_day(max_day: int) -> dict:
    """Cumulative shipped quantities 1..max_day."""
    max_day = int(max_day or 0)
    if max_day <= 0:
        return {}
    df_sales = load_sales_log()
    df_ship = _sales_shipped_by_day(df_sales)
    if df_ship.empty:
        return {}
    df_ship = df_ship[(df_ship['Day'] >= 1) & (df_ship['Day'] <= max_day)]
    if df_ship.empty:
        return {}
    grouped = df_ship.groupby('Product', as_index=False)['ShippedQty'].sum()
    return {str(r['Product']).strip(): int(round(float(r['ShippedQty'] or 0.0))) for _, r in grouped.iterrows() if float(r['ShippedQty'] or 0.0) > 0}


def _material_cost_from_ledger_for_day(day: int) -> float:
    if day <= 0:
        return 0.0
    unit_costs = get_material_unit_costs()
    df = load_production_ledger()
    if df.empty or not {'day', 'type', 'sku', 'qty'}.issubset(df.columns):
        return _material_cost_from_state_for_day(day)
    df_day = df[(df['day'] == int(day)) & (df['type'] == 'consume')]
    if df_day.empty:
        return _material_cost_from_state_for_day(day)
    def _unit_cost(sku: str) -> float:
        return float(unit_costs.get(str(sku).strip(), 0.0) or 0.0)
    costs = (df_day['qty'] * df_day['sku'].map(_unit_cost)).sum()
    return float(costs or 0.0)


def procurement_cost_for_day(day: int) -> float:
    """Real purchase cost: sum(quantity * unit_cost + order_cost) for orders placed on a day."""
    day = int(day or 0)
    if day <= 0:
        return 0.0
    params = get_material_procurement_cost_params()
    df = load_bestellungen()
    if df.empty or not {'Bestelltag', 'Material', 'Menge'}.issubset(df.columns):
        return 0.0
    df_day = df[df['Bestelltag'] == day]
    if df_day.empty:
        return 0.0

    # Count order_cost once per Bestell_ID if present; else per row.
    total = 0.0
    if 'Bestell_ID' in df_day.columns and df_day['Bestell_ID'].astype(str).str.strip().ne('').any():
        for order_id, grp in df_day.groupby(df_day['Bestell_ID'].astype(str).str.strip()):
            if not order_id:
                continue
            # variable costs
            for _, row in grp.iterrows():
                mat = str(row.get('Material', '')).strip()
                qty = int(row.get('Menge', 0) or 0)
                unit_cost = float(params.get(mat, {}).get('unit_cost_eur', 0.0) or 0.0)
                total += float(qty) * unit_cost
            # fixed order cost: use first material's param if available
            mat0 = str(grp.iloc[0].get('Material', '')).strip()
            total += float(params.get(mat0, {}).get('order_cost_eur', 0.0) or 0.0)
    else:
        for _, row in df_day.iterrows():
            mat = str(row.get('Material', '')).strip()
            qty = int(row.get('Menge', 0) or 0)
            unit_cost = float(params.get(mat, {}).get('unit_cost_eur', 0.0) or 0.0)
            order_cost = float(params.get(mat, {}).get('order_cost_eur', 0.0) or 0.0)
            total += float(qty) * unit_cost + order_cost

    return float(total or 0.0)


def _material_cost_by_product_for_day(day: int) -> dict:
    """Allocate consumed material cost to for_product if available."""
    if day <= 0:
        return {}
    unit_costs = get_material_unit_costs()
    df = load_production_ledger()
    if df.empty or not {'day', 'type', 'sku', 'qty', 'for_product'}.issubset(df.columns):
        return {}
    df_day = df[(df['day'] == int(day)) & (df['type'] == 'consume')]
    if df_day.empty:
        return {}

    def _unit_cost(sku: str) -> float:
        return float(unit_costs.get(str(sku).strip(), 0.0) or 0.0)

    df_day = df_day.copy()
    df_day['line_cost'] = df_day['qty'] * df_day['sku'].map(_unit_cost)
    # Only allocate when for_product is present
    df_day['for_product'] = df_day['for_product'].astype(str).str.strip()
    df_day = df_day[df_day['for_product'] != '']
    if df_day.empty:
        return {}

    grouped = df_day.groupby('for_product', as_index=False)['line_cost'].sum()
    return {str(r['for_product']): float(r['line_cost'] or 0.0) for _, r in grouped.iterrows()}


def produced_fg_qty_for_day(day: int) -> int:
    """Produced qty for a day.

    Preferred source: production_ledger.csv (FG produce lines).
    Fallback: executed production qty from simulation_state.pkl (Loop A + Loop B).
    """
    if day <= 0:
        return 0
    fg_names = set(load_unit_prices().keys())
    df = load_production_ledger()
    if df.empty or not {'day', 'type', 'sku', 'qty'}.issubset(df.columns):
        return _executed_qty_from_state_for_day(day)
    df_day = df[(df['day'] == int(day)) & (df['type'] == 'produce')]
    if df_day.empty:
        return _executed_qty_from_state_for_day(day)
    df_day = df_day[df_day['sku'].astype(str).str.strip().isin(fg_names)]
    if df_day.empty:
        return _executed_qty_from_state_for_day(day)
    qty = int(round(float(df_day['qty'].sum() or 0.0)))
    return qty if qty > 0 else _executed_qty_from_state_for_day(day)


def produced_fg_qty_up_to_day(max_day: int) -> int:
    max_day = int(max_day or 0)
    if max_day <= 0:
        return 0
    fg_names = set(load_unit_prices().keys())
    df = load_production_ledger()
    if df.empty or not {'day', 'type', 'sku', 'qty'}.issubset(df.columns):
        return sum(_executed_qty_from_state_for_day(d) for d in range(1, max_day + 1))
    df2 = df[(df['day'] >= 1) & (df['day'] <= max_day) & (df['type'] == 'produce')]
    if df2.empty:
        return sum(_executed_qty_from_state_for_day(d) for d in range(1, max_day + 1))
    df2 = df2[df2['sku'].astype(str).str.strip().isin(fg_names)]
    if df2.empty:
        return sum(_executed_qty_from_state_for_day(d) for d in range(1, max_day + 1))
    qty = int(round(float(df2['qty'].sum() or 0.0)))
    return qty if qty > 0 else sum(_executed_qty_from_state_for_day(d) for d in range(1, max_day + 1))


def calculate_daily_financials_from_logs(day: int) -> dict:
    """Daily P&L for a logical day d.

    - Revenue: shipments(d) from sales_log.csv
    - Procurement cost: orders placed(d) from bestellungen.csv (real cash/expense driver)
    - Consumption cost: material consumed(d) from production_ledger.csv (for transparency)
    - Profit: revenue - procurement_cost
    """
    if day <= 0:
        return {
            'revenue': 0.0,
            'procurement_cost': 0.0,
            'consumption_cost': 0.0,
            'cost': 0.0,
            'profit': 0.0,
            'margin': 0.0,
            'products_sold': 0
        }

    unit_prices = load_unit_prices()
    shipped = shipped_quantities_for_day(day)

    revenue = 0.0
    products_sold = 0
    for prod, qty in shipped.items():
        if qty <= 0:
            continue
        revenue += float(unit_prices.get(prod, 0.0) or 0.0) * float(qty)
        products_sold += int(qty)

    procurement = procurement_cost_for_day(day)
    consumption = _material_cost_from_ledger_for_day(day)

    # Profit uses procurement as "real" cost driver
    profit = revenue - procurement
    margin = (profit / revenue * 100) if revenue > 0 else 0.0

    return {
        'revenue': float(revenue),
        'procurement_cost': float(procurement),
        'consumption_cost': float(consumption),
        # keep legacy key for callers; represent procurement cost
        'cost': float(procurement),
        'profit': float(profit),
        'margin': float(margin),
        'products_sold': int(products_sold)
    }


def build_financial_history_from_logs(max_day: int) -> list:
    history = []
    for d in range(1, int(max_day) + 1):
        f = calculate_daily_financials_from_logs(d)
        history.append({'day': d, **f})
    return history

# ============================================================================
# KPI Kacheln
# ============================================================================

def create_kpi_card(title, value, unit='€', color='#51CF66', icon='💰', trend=None, trend_value=None):
    """Erstelle eine moderne KPI-Kachel"""
    trend_element = None
    if trend is not None:
        trend_color = '#51CF66' if trend == 'up' else '#FF6B6B'
        trend_icon = '↑' if trend == 'up' else '↓'
        trend_element = html.Div([
            html.Span(trend_icon, style={'marginRight': '4px'}),
            html.Span(f'{trend_value}', style={'fontSize': '0.85rem'})
        ], style={'color': trend_color, 'fontWeight': '600', 'marginTop': '0.5rem'})
    
    return html.Div([
        html.Div([
            html.Span(icon, style={'fontSize': '1.5rem'}),
            html.Span(title, style={'marginLeft': '0.5rem', 'fontSize': '0.9rem', 'color': '#6a6a7a'})
        ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '0.75rem'}),
        html.Div([
            html.Span(f'{value:,.0f}' if isinstance(value, (int, float)) else value, 
                     style={'fontSize': '2rem', 'fontWeight': '700', 'color': color}),
            html.Span(f' {unit}', style={'fontSize': '1rem', 'color': '#9a9aaa', 'marginLeft': '4px'})
        ]),
        trend_element if trend_element else None
    ], className='finance-kpi-card')

# ============================================================================
# Charts
# ============================================================================

def create_revenue_cost_chart(history_data):
    """Erstelle Umsatz/Kosten/Gewinn Chart über Zeit"""
    
    if not history_data or len(history_data) == 0:
        fig = go.Figure()
        fig.add_annotation(text="Keine Daten - Starte die Simulation", 
                          xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(
            height=350,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        return fig
    
    days = [d.get('day') for d in history_data]
    revenues = [d.get('revenue', 0) for d in history_data]
    procurement_costs = [d.get('procurement_cost', d.get('cost', 0)) for d in history_data]
    consumption_costs = [d.get('consumption_cost', 0) for d in history_data]
    profits = [d.get('profit', 0) for d in history_data]
    
    fig = go.Figure()
    
    # Umsatz
    fig.add_trace(go.Scatter(
        x=days, y=revenues,
        name='Umsatz',
        line=dict(color='#3498db', width=3),
        fill='tozeroy',
        fillcolor='rgba(52, 152, 219, 0.1)'
    ))
    
    # Einkaufskosten (real)
    fig.add_trace(go.Scatter(
        x=days, y=procurement_costs,
        name='Einkaufskosten',
        line=dict(color='#e74c3c', width=3),
        fill='tozeroy',
        fillcolor='rgba(231, 76, 60, 0.1)'
    ))

    # Materialverbrauchskosten (transparent)
    fig.add_trace(go.Scatter(
        x=days, y=consumption_costs,
        name='Materialverbrauch (Verbrauch)',
        line=dict(color='#f39c12', width=3, dash='dash')
    ))
    
    # Gewinn
    fig.add_trace(go.Scatter(
        x=days, y=profits,
        name='Gewinn',
        line=dict(color='#2ecc71', width=3, dash='dot')
    ))
    
    fig.update_layout(
        title='📈 Finanzentwicklung über Zeit',
        xaxis_title='Tag',
        yaxis_title='Betrag (€)',
        height=350,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        hovermode='x unified',
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(gridcolor='rgba(0,0,0,0.1)'),
        yaxis=dict(gridcolor='rgba(0,0,0,0.1)', tickformat=',.0f')
    )
    
    return fig

def create_cumulative_chart(history_data):
    """Erstelle kumulativen Gewinn/Verlust Chart"""
    
    if not history_data or len(history_data) == 0:
        fig = go.Figure()
        fig.add_annotation(text="Keine Daten", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(height=300, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        return fig
    
    days = list(range(1, len(history_data) + 1))
    cumulative_profit = []
    running_total = 0
    
    for d in history_data:
        running_total += d.get('profit', 0)
        cumulative_profit.append(running_total)
    
    colors = ['#2ecc71' if p >= 0 else '#e74c3c' for p in cumulative_profit]
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=days, y=cumulative_profit,
        name='Kumulativer Gewinn',
        marker_color=colors
    ))
    
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    
    fig.update_layout(
        title='💰 Kumulativer Gewinn/Verlust',
        xaxis_title='Tag',
        yaxis_title='Kumulativer Gewinn (€)',
        height=300,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(gridcolor='rgba(0,0,0,0.1)'),
        yaxis=dict(gridcolor='rgba(0,0,0,0.1)', tickformat=',.0f')
    )
    
    return fig

def create_product_breakdown_chart(daily_shipments):
    """Erstelle Produktverteilungs-Chart"""
    
    if not daily_shipments or not isinstance(daily_shipments, dict) or sum(daily_shipments.values()) == 0:
        fig = go.Figure()
        fig.add_annotation(text="Keine Daten", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(height=300, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        return fig
    
    unit_prices = load_unit_prices()
    
    products = []
    quantities = []
    revenues = []
    colors = ['#3498db', '#9b59b6', '#1abc9c', '#e74c3c', '#f39c12', '#e91e63']
    
    for i, (product, qty) in enumerate(daily_shipments.items()):
        if qty > 0:
            products.append(product)
            quantities.append(qty)
            revenues.append(unit_prices.get(product, 0) * qty)
    
    fig = make_subplots(rows=1, cols=2, specs=[[{'type': 'domain'}, {'type': 'domain'}]],
                        subplot_titles=['Stückzahlen', 'Umsatzverteilung'])
    
    fig.add_trace(go.Pie(
        labels=products, values=quantities,
        hole=0.4, marker_colors=colors[:len(products)],
        textinfo='label+value'
    ), row=1, col=1)
    
    fig.add_trace(go.Pie(
        labels=products, values=revenues,
        hole=0.4, marker_colors=colors[:len(products)],
        textinfo='label+percent'
    ), row=1, col=2)
    
    fig.update_layout(
        title='📦 Produktverteilung (gesamt)',
        height=300,
        paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False
    )
    
    return fig

def create_cost_breakdown_table(daily_shipments, day_for_cost_allocation: int):
    """Erstelle Kostenaufschlüsselung als Tabelle"""
    
    if not daily_shipments or not isinstance(daily_shipments, dict):
        return html.Div("Keine Daten", style={'padding': '1rem', 'color': '#999'})
    
    unit_prices = load_unit_prices()
    cost_by_product = _material_cost_by_product_for_day(int(day_for_cost_allocation))
    rows = []
    total_revenue = 0
    total_cost = 0
    
    for product_id, qty in sorted(daily_shipments.items()):
        if qty > 0:
            price = unit_prices.get(product_id, 0)
            revenue = price * qty
            total_cost_prod = float(cost_by_product.get(product_id, 0.0) or 0.0)
            profit = revenue - total_cost_prod
            margin = (profit / revenue * 100) if revenue > 0 else 0
            
            total_revenue += revenue
            total_cost += total_cost_prod
            
            rows.append(html.Tr([
                html.Td(product_id, style={'fontWeight': '600'}),
                html.Td(f'{qty}', style={'textAlign': 'center'}),
                html.Td(f'{price:,.0f} €', style={'textAlign': 'right'}),
                html.Td(f'{revenue:,.0f} €', style={'textAlign': 'right', 'color': '#3498db'}),
                html.Td(f'{total_cost_prod:,.0f} €', style={'textAlign': 'right', 'color': '#e74c3c'}),
                html.Td(f'{profit:,.0f} €', style={'textAlign': 'right', 'color': '#2ecc71' if profit >= 0 else '#e74c3c', 'fontWeight': '600'}),
                html.Td(f'{margin:.1f}%', style={'textAlign': 'right'})
            ]))
    
    # Total Row
    total_profit = total_revenue - total_cost
    total_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    rows.append(html.Tr([
        html.Td('GESAMT', style={'fontWeight': '700', 'backgroundColor': '#f8f9fa'}),
        html.Td(f'{sum(daily_shipments.values())}', style={'textAlign': 'center', 'fontWeight': '700', 'backgroundColor': '#f8f9fa'}),
        html.Td('', style={'backgroundColor': '#f8f9fa'}),
        html.Td(f'{total_revenue:,.0f} €', style={'textAlign': 'right', 'fontWeight': '700', 'color': '#3498db', 'backgroundColor': '#f8f9fa'}),
        html.Td(f'{total_cost:,.0f} €', style={'textAlign': 'right', 'fontWeight': '700', 'color': '#e74c3c', 'backgroundColor': '#f8f9fa'}),
        html.Td(f'{total_profit:,.0f} €', style={'textAlign': 'right', 'fontWeight': '700', 'color': '#2ecc71' if total_profit >= 0 else '#e74c3c', 'backgroundColor': '#f8f9fa'}),
        html.Td(f'{total_margin:.1f}%', style={'textAlign': 'right', 'fontWeight': '700', 'backgroundColor': '#f8f9fa'})
    ]))
    
    header = html.Tr([
        html.Th('Produkt'),
        html.Th('Shipped'),
        html.Th('VK-Preis'),
        html.Th('Umsatz'),
        html.Th('Materialkosten'),
        html.Th('Gewinn'),
        html.Th('Marge')
    ])
    
    return html.Table([html.Thead(header), html.Tbody(rows)], className='finance-table')

# ============================================================================
# Hauptlayout
# ============================================================================

def layout():
    """Finanz-Dashboard Layout"""
    
    return html.Div([
        html.H2('💰 Finanzen & Kostenanalyse', style={'marginBottom': '0.5rem', 'color': '#1a1a2e'}),
        html.P('Umsatz basiert auf tatsächlichen Verkäufen (Shipments). Gewinn wird um Einkaufskosten reduziert; Materialverbrauch wird separat transparent ausgewiesen (keine Lohn-/Overheadkosten).',
               style={'color': '#6a6a7a', 'marginBottom': '1.5rem'}),
        
        # === GESAMT-KPIs (Kumulativ) ===
        html.H4('📊 Gesamtübersicht (alle simulierten Tage)', style={'marginBottom': '0.75rem', 'color': '#1a1a2e', 'marginTop': '0.5rem'}),
        html.Div([
            html.Div(id='kpi-total-revenue', children=[create_kpi_card('Gesamtumsatz', 0, '€', '#2980b9', '💵')]),
            html.Div(id='kpi-total-cost', children=[create_kpi_card('Gesamtkosten (Einkauf)', 0, '€', '#c0392b', '📊')]),
            html.Div(id='kpi-total-material-cost', children=[create_kpi_card('Gesamtkosten (Materialverbrauch)', 0, '€', '#e67e22', '🧱')]),
            html.Div(id='kpi-total-profit', children=[create_kpi_card('Gesamtgewinn', 0, '€', '#27ae60', '🏆')]),
            html.Div(id='kpi-total-products', children=[create_kpi_card('Produziert', 0, 'Stk', '#d35400', '🏭')]),
            html.Div(id='kpi-avg-margin', children=[create_kpi_card('Ø Marge', 0, '%', '#8e44ad', '📈')]),
            html.Div(id='kpi-total-service-level', children=[create_kpi_card('Service Level (gesamt)', 0, '%', '#16a085', '✅')]),
        ], className='finance-kpi-grid', style={'marginBottom': '1.5rem'}),
        
        html.Hr(style={'margin': '1.5rem 0', 'borderColor': '#e0e0e0'}),
        
        # === TAGES-KPIs ===
        html.H4('📅 Tageswerte (Vortag / zuletzt abgeschlossener Tag)', style={'marginBottom': '0.75rem', 'color': '#1a1a2e'}),
        html.Div([
            html.Div(id='kpi-revenue', children=[create_kpi_card('Umsatz (Vortag)', 0, '€', '#3498db', '📈')]),
            html.Div(id='kpi-cost', children=[create_kpi_card('Einkaufskosten (Vortag)', 0, '€', '#e74c3c', '📉')]),
            html.Div(id='kpi-material-cost', children=[create_kpi_card('Materialkosten (Vortag, Verbrauch)', 0, '€', '#e67e22', '🧱')]),
            html.Div(id='kpi-profit', children=[create_kpi_card('Gewinn (Vortag)', 0, '€', '#2ecc71', '💰')]),
            html.Div(id='kpi-products', children=[create_kpi_card('Produziert (Vortag)', 0, 'Stk', '#f39c12', '📦')]),
            html.Div(id='kpi-margin', children=[create_kpi_card('Marge (Vortag)', 0, '%', '#9b59b6', '📊')]),
            html.Div(id='kpi-service-level', children=[create_kpi_card('Service Level (Vortag)', 0, '%', '#16a085', '✅')]),
        ], className='finance-kpi-grid'),
        
        # Charts Row 1
        html.Div([
            html.Div([
                dcc.Graph(id='finance-revenue-cost-chart', figure=create_revenue_cost_chart([]))
            ], className='finance-chart-card', style={'flex': '2'}),
            
            html.Div([
                dcc.Graph(id='finance-cumulative-chart', figure=create_cumulative_chart([]))
            ], className='finance-chart-card', style={'flex': '1'}),
        ], className='finance-charts-row'),
        
        # Charts Row 2 & Table
        html.Div([
            html.Div([
                dcc.Graph(id='finance-product-chart', figure=create_product_breakdown_chart({}))
            ], className='finance-chart-card'),
        ], className='finance-charts-row'),
        
        # Hidden Store für Finanzhistorie (nicht mehr verwendet, aber für Kompatibilität)
        dcc.Store(id='finance-history', data=[]),
        
    ], className='finance-container')


# ============================================================================
# Callbacks
# ============================================================================

@callback(
    [Output('kpi-total-revenue', 'children'),
     Output('kpi-total-cost', 'children'),
    Output('kpi-total-material-cost', 'children'),
     Output('kpi-total-profit', 'children'),
     Output('kpi-total-products', 'children'),
     Output('kpi-avg-margin', 'children'),
    Output('kpi-total-service-level', 'children'),
     Output('kpi-revenue', 'children'),
     Output('kpi-cost', 'children'),
    Output('kpi-material-cost', 'children'),
     Output('kpi-profit', 'children'),
     Output('kpi-margin', 'children'),
     Output('kpi-products', 'children'),
    Output('kpi-service-level', 'children'),
     Output('finance-revenue-cost-chart', 'figure'),
     Output('finance-cumulative-chart', 'figure'),
     Output('finance-product-chart', 'figure'),
     Output('finance-history', 'data')],
    [Input('global-simulation-state', 'data')],
    [State('finance-history', 'data')],
    prevent_initial_call=False
)
def update_finance_dashboard(global_state, history):
    """Aktualisiere das Finanz-Dashboard basierend auf der globalen Simulation"""

    current_day = 1
    if global_state and isinstance(global_state, dict):
        current_day = int(global_state.get('day', 1) or 1)

    # Shipments (Umsatz) werden beim Klick auf "Nächster Tag" geloggt.
    # Für Konsistenz zeigen wir alle Tageswerte immer für den Vortag (abgeschlossener Tag).
    day_prev = max(0, current_day - 1)

    # Tageswerte (Vortag) aus Logs
    financials_prev = calculate_daily_financials_from_logs(day_prev)
    produced_prev = produced_fg_qty_for_day(day_prev)

    # Historie/Total zeigen wir konservativ bis zum Vortag (abgeschlossene Tage)
    full_history = build_financial_history_from_logs(day_prev)
    chart_history = [
        {
            'day': d.get('day'),
            'revenue': d.get('revenue', 0),
            'procurement_cost': d.get('procurement_cost', d.get('cost', 0)),
            'consumption_cost': d.get('consumption_cost', 0),
            'cost': d.get('cost', 0),
            'profit': d.get('profit', 0)
        }
        for d in full_history
    ]

    total_revenue = sum(d.get('revenue', 0) for d in full_history)
    total_procurement_cost = sum(d.get('procurement_cost', d.get('cost', 0)) for d in full_history)
    total_consumption_cost = sum(d.get('consumption_cost', 0) for d in full_history)
    total_profit = sum(d.get('profit', 0) for d in full_history)
    total_products = produced_fg_qty_up_to_day(day_prev)
    avg_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
    total_service_level = service_level_up_to_day(day_prev)
    
    # === GESAMT-KPIs ===
    total_revenue_kpi = create_kpi_card('Gesamtumsatz', total_revenue, '€', '#2980b9', '💵')
    total_cost_kpi = create_kpi_card('Gesamtkosten (Einkauf)', total_procurement_cost, '€', '#c0392b', '📊')
    total_material_cost_kpi = create_kpi_card('Gesamtkosten (Materialverbrauch)', total_consumption_cost, '€', '#e67e22', '🧱')
    total_profit_kpi = create_kpi_card('Gesamtgewinn', total_profit, '€', 
                                        '#27ae60' if total_profit >= 0 else '#c0392b', '🏆')
    total_products_kpi = create_kpi_card('Produziert', total_products, 'Stk', '#d35400', '🏭')
    avg_margin_kpi = create_kpi_card('Ø Marge', avg_margin, '%', '#8e44ad', '📈')
    total_service_kpi = create_kpi_card('Service Level (gesamt)', total_service_level, '%', '#16a085', '✅')
    
    # === TAGES-KPIs ===
    # Umsatz/Gewinn: Vortag (aus Shipments)
    revenue_kpi = create_kpi_card('Umsatz (Vortag)', financials_prev['revenue'], '€', '#3498db', '📈')
    cost_kpi = create_kpi_card('Einkaufskosten (Vortag)', financials_prev.get('procurement_cost', financials_prev['cost']), '€', '#e74c3c', '📉')
    material_cost_kpi = create_kpi_card('Materialkosten (Vortag, Verbrauch)', financials_prev.get('consumption_cost', 0.0), '€', '#e67e22', '🧱')
    profit_kpi = create_kpi_card('Gewinn (Vortag)', financials_prev['profit'], '€',
                                  '#2ecc71' if financials_prev['profit'] >= 0 else '#e74c3c', '💰')
    margin_kpi = create_kpi_card('Marge (Vortag)', financials_prev['margin'], '%', '#9b59b6', '📊')
    products_kpi = create_kpi_card('Produziert (Vortag)', produced_prev, 'Stk', '#f39c12', '📦')
    service_kpi = create_kpi_card('Service Level (Vortag)', service_level_for_day(day_prev), '%', '#16a085', '✅')
    
    # Charts (aus Server-Historie)
    revenue_cost_chart = create_revenue_cost_chart(chart_history)
    cumulative_chart = create_cumulative_chart(chart_history)
    shipped_total = shipped_quantities_up_to_day(day_prev)
    product_chart = create_product_breakdown_chart(shipped_total)
    
    return (
        total_revenue_kpi,
        total_cost_kpi,
        total_material_cost_kpi,
        total_profit_kpi,
        total_products_kpi,
        avg_margin_kpi,
        total_service_kpi,
        revenue_kpi,
        cost_kpi,
        material_cost_kpi,
        profit_kpi,
        margin_kpi,
        products_kpi,
        service_kpi,
        revenue_cost_chart,
        cumulative_chart,
        product_chart,
        chart_history  # Für Kompatibilität im Store
    )
