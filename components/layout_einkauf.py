"""
components/layout_einkauf.py

Einkauf-Tab für Material-Bestellungen mit Lieferzeiten.
"""

import pandas as pd
from dash import html, dcc, callback, Input, Output, State, ALL, ctx
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime
import uuid

from utils.overflow_simulator import (
    load_or_create_material_fill_levels,
    load_material_buffer_zones,
    get_material_zone,
    load_or_create_simulation_state,
    load_bom_from_csv,
    calculate_material_consumption
)

# Gemeinsame Reorder-Regeln (s, q) für Auto-Bestellungen
# Standard-Regeln (legacy s/q)
AUTO_RULES_LEGACY = {
    "Dichtungsringe": {"s": 828, "q": 7200},
    "Schrauben": {"s": 1848, "q": 13470},
}

# ToY-basierte Reorderpunkte aus pufferzonen.csv

def load_toy_rules_from_csv():
    """
 Lade DDMRP-Pufferregeln aus CSV.

    - reorder_point = ToY (Yellow + Total Red)
    - target_buffer = Total Buffer (Red + Yellow + Green)

    Die tatsächliche Bestellmenge wird später dynamisch berechnet als:
    order_qty = target_buffer - net_flow_position
    """
    toy_path = Path(__file__).parent.parent / 'data' / 'raw' / 'pufferzonen.csv'
    toy_fallback_path = Path(__file__).parent.parent / 'data' / 'raw' / 'material_pufferzonen.csv'
    rules = {}

    try:
        df = pd.read_csv(toy_path, index_col=0)
        item_row = df.loc['Item']
        toy_row = df.loc['ToY (Reorder point)']
        total_row = df.loc['Total Buffer [pcs]']
        adu = df.loc['Average Daily Usage [pcs]']
        dlt = df.loc['Demand Lead Time [days]']

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
            target_buffer = pd.to_numeric(total_row.get(col), errors='coerce')

            if pd.isna(reorder_point) or pd.isna(target_buffer):
                continue

            rules[material] = {
                "reorder_point": int(reorder_point),
                "target_buffer": int(target_buffer)
            }

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
            rules[material] = {
                "reorder_point": int(yellow + red),          # ToY
                "target_buffer": int(green + yellow + red)   # Target Buffer
            }

    except Exception:
        pass

    return rules

def load_average_daily_usage():
    """
    Lade ADU (Average Daily Usage) aus pufferzonen.csv für Nachfrage-Abschätzungen.
    """
    toy_path = Path(__file__).parent.parent / 'data' / 'raw' / 'pufferzonen.csv'
    adu_map = {}

    try:
        df = pd.read_csv(toy_path, index_col=0)
        item_row = df.loc['Item']
        adu_row = df.loc['ADU [pcs/day]']

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

            raw_val = str(adu_row.get(col, '')).replace(',', '.')
            adu_val = pd.to_numeric(raw_val, errors='coerce')
            if pd.isna(adu_val):
                continue
            adu_map[material] = float(adu_val)
    except Exception:
        pass

    return adu_map

def load_simulated_orders_df():
    """Lade simulated_orders.csv (Forecast/Order-Plan)."""
    csv_path = Path(__file__).parent.parent / 'data' / 'simulated_orders.csv'
    try:
        df = pd.read_csv(csv_path)
        return df
    except Exception:
        return pd.DataFrame(columns=['Day'])

def load_product_daily_forecast():
    """
    Fallback-Forecast je Produkt (Durchschnittliche Nachfrage/Tag).
    Quelle: Demand_Simulation.csv.
    """
    csv_path = Path(__file__).parent.parent / 'data' / 'raw' / 'Demand_Simulation.csv'
    forecast = {}
    try:
        df = pd.read_csv(csv_path)
        for _, row in df.iterrows():
            product = str(row.get('Produkt', '')).strip()
            if not product:
                continue
            raw_val = str(row.get('Durchschnittliche_Nachfrage_taeglich', '')).replace(',', '.')
            val = pd.to_numeric(raw_val, errors='coerce')
            if pd.isna(val):
                continue
            forecast[product] = int(round(float(val)))
    except Exception:
        pass
    return forecast

def load_recent_capacity_daily_material_consumption(days: int = 5, bom_df: pd.DataFrame = None) -> dict:
    """
    Schätze tägliche Materialnachfrage basierend auf tatsächlicher Produktion.
    Fallback: geplante Produktion, falls keine Ist-Daten vorliegen.
    """
    state = load_or_create_simulation_state()
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

    orders_df = orders_df if orders_df is not None else load_simulated_orders_df()
    fallback_forecast = fallback_forecast if fallback_forecast is not None else load_product_daily_forecast()
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

def calculate_net_flow_position(
    material: str,
    current_level: int,
    current_day: int,
    lead_time_days: int,
    adu_map=None,
    expected_demand: int = None
) -> int:
    """
    Net Flow Position = On-hand + zeitnahe Open Supply - erwarteter Verbrauch bis Lieferung.
    """
    bestellungen = load_bestellungen()
    lead_time_days = max(int(lead_time_days or 0), 0)

    window_end = current_day + lead_time_days

    offene = pd.DataFrame()
    if not bestellungen.empty:
        offene = bestellungen[
            (bestellungen['Material'] == material) &
            (bestellungen['Status'] == 'offen') &
            (bestellungen['Liefertag'] <= window_end)
        ]

    open_supply = offene['Menge'].sum() if not offene.empty else 0
    if expected_demand is None:
        adu = adu_map.get(material, 0) if adu_map else 0
        expected_demand = adu * lead_time_days

    return current_level + open_supply - expected_demand

def calculate_order_qty(rule, net_flow_position):
    """
    DDMRP order quantity calculation.
    """
    if net_flow_position <= rule["reorder_point"]:
        return max(0, rule["target_buffer"] - net_flow_position)
    return 0

# ============================================================================
# Data Loading
# ============================================================================

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

def has_open_order(material: str) -> bool:
    bestellungen = load_bestellungen()
    if bestellungen.empty:
        return False

    offene = bestellungen[
        (bestellungen["Material"] == material) &
        (bestellungen["Status"] == "offen")
    ]
    return not offene.empty

def save_bestellungen(df):
    """Speichere Bestellungen in CSV"""
    csv_path = Path(__file__).parent.parent / 'data' / 'bestellungen.csv'
    df.to_csv(csv_path, index=False)


def add_bestellung(material: str, menge: int, current_day: int):
    """Füge neue Bestellung hinzu"""
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


def auto_reorder_materials(current_day: int) -> list:
    """
    Vereinfachte Reorder-Logik:

    - Trigger NUR auf On-hand ≤ ToY
    - Wenn offene Bestellung existiert → warten
    - Nach Wareneingang:
        falls Bestand weiter ≤ ToY → erneut bestellen
    """
    created = []

    fill_levels = load_or_create_material_fill_levels()
    lieferzeiten = load_lieferzeiten()
    orders_df = load_simulated_orders_df()
    fallback_forecast = load_product_daily_forecast()
    bom_df = load_bom_from_csv()
    capacity_daily = load_recent_capacity_daily_material_consumption(days=5, bom_df=bom_df)
    toy_rules = load_toy_rules_from_csv()

    # -------------------------------
    # 1) Legacy-Materialien (s / q)
    # -------------------------------
    for material, cfg in AUTO_RULES_LEGACY.items():
        current_level = fill_levels.get(material, 0)

        if current_level <= cfg["s"] and not has_open_order(material):
            add_bestellung(material, cfg["q"], current_day)
            created.append(material)

    # -------------------------------
    # 2) DDMRP-Materialien (ToY)
    # -------------------------------
    for material, rule in toy_rules.items():
        current_level = fill_levels.get(material, 0)

        # 👉 WICHTIG: Wenn Bestellung offen → NICHTS tun
        if has_open_order(material):
            continue

        # 👉 Trigger ausschließlich auf On-hand
        if current_level > rule["reorder_point"]:
            continue

        # Lieferzeit (für Mengenberechnung)
        lead_time = lieferzeiten.get(material, {}).get("Lieferzeit_Tage", 5)

        # Net Flow Position NUR für Mengenhöhe
        expected_demand = calculate_expected_material_demand(
            material=material,
            current_day=current_day,
            lead_time_days=lead_time,
            orders_df=orders_df,
            fallback_forecast=fallback_forecast,
            bom_df=bom_df,
            capacity_daily=capacity_daily
        )

        nfp = calculate_net_flow_position(
            material=material,
            current_level=current_level,
            current_day=current_day,
            lead_time_days=lead_time,
            expected_demand=expected_demand
        )

        order_qty = max(0, rule["target_buffer"] - nfp)

        # Mindestbestellmenge beachten
        min_qty = lieferzeiten.get(material, {}).get("Mindestbestellmenge", 0)
        if min_qty:
            order_qty = max(order_qty, int(min_qty))

        if order_qty > 0:
            add_bestellung(material, int(order_qty), current_day)
            created.append(material)

    return created

def create_material_status_cards():
    """Erstelle Material-Status-Karten mit Bestellmöglichkeit"""
    
    fill_levels = load_or_create_material_fill_levels()
    material_zones = load_material_buffer_zones()
    lieferzeiten = load_lieferzeiten()
    
    # Alle Materialien (aus Lieferzeiten, da das die bestellbaren sind)
    all_materials = list(lieferzeiten.keys())
    
    cards = []
    for material in all_materials:
        # Füllstand (falls vorhanden)
        fill = fill_levels.get(material, 0)
        
        # Zone bestimmen
        zone = get_material_zone(material, fill) if material in material_zones else 'N/A'
        zone_color = {'RED': '#FF6B6B', 'YELLOW': '#FFD700', 'GREEN': '#51CF66'}.get(zone, '#999')
        
        # Lieferzeit
        lieferzeit = lieferzeiten.get(material, {}).get('Lieferzeit_Tage', '?')
        min_menge = lieferzeiten.get(material, {}).get('Mindestbestellmenge', 0)
        lieferant = lieferzeiten.get(material, {}).get('Lieferant', 'Unbekannt')
        
        # Zone-Info
        zones = material_zones.get(material, {})
        total = zones.get('total', 0)
        
        card = html.Div([
            # Header mit Material-Name und Zone
            html.Div([
                html.H4(material, style={'margin': '0', 'color': '#2c3e50'}),
                html.Span(zone, style={
                    'backgroundColor': zone_color,
                    'color': 'white',
                    'padding': '0.2rem 0.6rem',
                    'borderRadius': '4px',
                    'fontSize': '0.8rem',
                    'fontWeight': 'bold'
                })
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center', 'marginBottom': '1rem'}),
            
            # Füllstand-Anzeige
            html.Div([
                html.Div([
                    html.Span("Aktueller Bestand: ", style={'color': '#666'}),
                    html.Span(f"{fill} pcs", style={'fontWeight': 'bold', 'color': '#2c3e50'})
                ]),
                html.Div([
                    html.Span("Kapazität: ", style={'color': '#666'}),
                    html.Span(f"{total} pcs", style={'color': '#2c3e50'})
                ]) if total > 0 else None
            ], style={'marginBottom': '1rem'}),
            
            # Lieferanten-Info
            html.Div([
                html.Div([
                    html.Span("🚚 Lieferzeit: ", style={'color': '#666'}),
                    html.Span(f"{lieferzeit} Tage", style={'fontWeight': 'bold', 'color': '#5A9FBF'})
                ]),
                html.Div([
                    html.Span("📦 Min. Menge: ", style={'color': '#666'}),
                    html.Span(f"{min_menge} pcs", style={'color': '#2c3e50'})
                ]),
                html.Div([
                    html.Span("🏭 Lieferant: ", style={'color': '#666', 'fontSize': '0.85rem'}),
                    html.Span(f"{lieferant}", style={'color': '#2c3e50', 'fontSize': '0.85rem'})
                ])
            ], style={'marginBottom': '1rem', 'fontSize': '0.9rem'}),
            
            # Bestellformular
            html.Div([
                dcc.Input(
                    id={'type': 'order-qty', 'material': material},
                    type='number',
                    placeholder=f'Menge (min. {min_menge})',
                    min=min_menge,
                    value=min_menge,
                    style={
                        'width': '100%',
                        'padding': '0.5rem',
                        'border': '1px solid #ddd',
                        'borderRadius': '4px',
                        'marginBottom': '0.5rem'
                    }
                ),
                html.Button(
                    '🛒 Bestellen',
                    id={'type': 'order-btn', 'material': material},
                    style={
                        'width': '100%',
                        'padding': '0.6rem',
                        'backgroundColor': '#5A9FBF',
                        'color': 'white',
                        'border': 'none',
                        'borderRadius': '4px',
                        'cursor': 'pointer',
                        'fontWeight': 'bold'
                    }
                )
            ])
        ], style={
            'backgroundColor': 'white',
            'padding': '1.5rem',
            'borderRadius': '8px',
            'boxShadow': '0 2px 8px rgba(0,0,0,0.1)',
            'border': f'3px solid {zone_color}',
            'minWidth': '280px'
        })
        
        cards.append(card)
    
    return cards


def create_pending_orders_table():
    """Erstelle Tabelle mit offenen Bestellungen"""
    df = load_bestellungen()
    
    if df.empty:
        return html.Div("Keine offenen Bestellungen", style={'color': '#666', 'fontStyle': 'italic', 'padding': '1rem'})
    
    # Nur offene Bestellungen
    df_open = df[df['Status'] == 'offen'].copy()
    
    if df_open.empty:
        return html.Div("Keine offenen Bestellungen", style={'color': '#666', 'fontStyle': 'italic', 'padding': '1rem'})
    
    rows = []
    for _, row in df_open.iterrows():
        tage_bis_lieferung = row['Liefertag'] - load_or_create_simulation_state().current_day
        
        rows.append(html.Tr([
            html.Td(row['Bestell_ID'], style={'padding': '0.6rem'}),
            html.Td(row['Material'], style={'padding': '0.6rem', 'fontWeight': 'bold'}),
            html.Td(f"{row['Menge']} pcs", style={'padding': '0.6rem', 'textAlign': 'center'}),
            html.Td(f"Tag {row['Bestelltag']}", style={'padding': '0.6rem', 'textAlign': 'center'}),
            html.Td(f"Tag {row['Liefertag']}", style={'padding': '0.6rem', 'textAlign': 'center'}),
            html.Td(
                html.Span(f"in {tage_bis_lieferung} Tagen" if tage_bis_lieferung > 0 else "Heute!",
                         style={
                             'backgroundColor': '#51CF66' if tage_bis_lieferung <= 1 else '#FFD700' if tage_bis_lieferung <= 3 else '#5A9FBF',
                             'color': 'white',
                             'padding': '0.3rem 0.6rem',
                             'borderRadius': '4px',
                             'fontSize': '0.85rem'
                         }),
                style={'padding': '0.6rem', 'textAlign': 'center'}
            )
        ], style={'borderBottom': '1px solid #eee'}))
    
    header = html.Tr([
        html.Th('Bestell-ID', style={'padding': '0.7rem', 'backgroundColor': '#5A9FBF', 'color': 'white', 'textAlign': 'left'}),
        html.Th('Material', style={'padding': '0.7rem', 'backgroundColor': '#5A9FBF', 'color': 'white', 'textAlign': 'left'}),
        html.Th('Menge', style={'padding': '0.7rem', 'backgroundColor': '#5A9FBF', 'color': 'white', 'textAlign': 'center'}),
        html.Th('Bestellt am', style={'padding': '0.7rem', 'backgroundColor': '#5A9FBF', 'color': 'white', 'textAlign': 'center'}),
        html.Th('Lieferung', style={'padding': '0.7rem', 'backgroundColor': '#5A9FBF', 'color': 'white', 'textAlign': 'center'}),
        html.Th('Status', style={'padding': '0.7rem', 'backgroundColor': '#5A9FBF', 'color': 'white', 'textAlign': 'center'})
    ])
    
    return html.Table([header] + rows, style={
        'width': '100%',
        'borderCollapse': 'collapse',
        'borderRadius': '8px',
        'overflow': 'hidden',
        'boxShadow': '0 2px 6px rgba(0,0,0,0.08)'
    })

# ============================================================================
# Main Layout
# ============================================================================

def layout():
    """Einkauf Layout"""
    
    return html.Div([
        html.H2('🛒 Einkauf & Bestellungen',
                style={
                    'marginBottom': '0.5rem', 
                    'color': '#1a1a2e',
                    'fontWeight': '700',
                    'fontSize': '1.75rem'
                }),
        
        html.Div(
            "Bestellen Sie Materialien bei Lieferanten. Bestellungen werden nach der jeweiligen Lieferzeit automatisch in den Bestand übernommen.",
            style={'marginBottom': '2rem', 'color': '#666', 'fontStyle': 'italic'}
        ),
        
        # Store für Bestellungs-Updates
        dcc.Store(id='einkauf-update-store', data=0),
        
        html.Div([
            html.Button(
                'Automatische Bestellungen: AN',
                id='auto-order-toggle',
                n_clicks=1,
                style={
                    'padding': '0.6rem 1rem',
                    'backgroundColor': '#51CF66',
                    'color': 'white',
                    'border': 'none',
                    'borderRadius': '6px',
                    'cursor': 'pointer',
                    'fontWeight': 'bold',
                    'boxShadow': '0 2px 6px rgba(0,0,0,0.1)'
                }
            )
        ], style={'marginBottom': '1.5rem'}),

        # Material-Karten
        html.H3('📦 Materialien bestellen', style={'marginBottom': '1rem', 'color': '#2c3e50'}),
        html.Div(
            id='material-cards-container',
            children=create_material_status_cards(),
            style={
                'display': 'flex',
                'flexWrap': 'wrap',
                'gap': '1.5rem',
                'marginBottom': '2rem'
            }
        ),
        
        # Offene Bestellungen
        html.Div([
            html.H3('📋 Offene Bestellungen', style={'marginBottom': '1rem', 'color': '#2c3e50'}),
            html.Div(id='pending-orders-container', children=[create_pending_orders_table()])
        ], style={
            'backgroundColor': 'white',
            'padding': '1.5rem',
            'borderRadius': '8px',
            'boxShadow': '0 2px 6px rgba(0,0,0,0.08)'
        })
        
    ], style={'padding': '2rem'})

# ============================================================================
# Callbacks
# ============================================================================

@callback(
    Output('pending-orders-container', 'children'),
    Output('material-cards-container', 'children'),
    Output('einkauf-update-store', 'data'),
    Output('auto-order-toggle', 'children'),
    Output('auto-order-toggle', 'style'),
    Input({'type': 'order-btn', 'material': ALL}, 'n_clicks'),
    State({'type': 'order-qty', 'material': ALL}, 'value'),
    Input('global-simulation-state', 'data'),
    Input('auto-order-toggle', 'n_clicks'),
    prevent_initial_call=True
)
def handle_order(n_clicks_list, qty_list, global_state, auto_clicks):
    """Handle Bestellungen"""
    
    triggered = ctx.triggered_id
    auto_enabled = (auto_clicks or 0) % 2 == 1  # odd = an, even = aus
    
    def toggle_style(enabled: bool):
        base = {
            'padding': '0.6rem 1rem',
            'border': 'none',
            'borderRadius': '6px',
            'cursor': 'pointer',
            'fontWeight': 'bold',
            'boxShadow': '0 2px 6px rgba(0,0,0,0.1)',
            'color': 'white'
        }
        if enabled:
            base.update({'backgroundColor': '#51CF66'})
        else:
            base.update({'backgroundColor': '#FF6B6B'})
        return base
    
    # Automatische Bestellungen auf globalen Simulations-Tick
    if triggered == 'global-simulation-state' and auto_enabled:
        current_day = (global_state or {}).get('current_day') if isinstance(global_state, dict) else None
        if current_day is None:
            current_day = load_or_create_simulation_state().current_day
        auto_reorder_materials(current_day)
    elif triggered == 'auto-order-toggle':
        # Toggle-Status ändern (nur visuell über Label-Farbe)
        pass
    
    if triggered and isinstance(triggered, dict) and triggered.get('type') == 'order-btn':
        material = triggered['material']
        
        # Finde die richtige Menge
        lieferzeiten = load_lieferzeiten()
        materials = list(lieferzeiten.keys())
        idx = materials.index(material) if material in materials else -1
        
        if idx >= 0 and qty_list[idx] and qty_list[idx] > 0:
            state = load_or_create_simulation_state()
            add_bestellung(material, qty_list[idx], state.current_day)
    
    button_label = f"Automatische Bestellungen: {'AN' if auto_enabled else 'AUS'}"
    button_style = toggle_style(auto_enabled)
    
    return create_pending_orders_table(), create_material_status_cards(), 1, button_label, button_style
