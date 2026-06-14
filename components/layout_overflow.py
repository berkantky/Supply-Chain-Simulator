"""
components/layout_overflow.py - Angepasste Version für Heijunka Overflow-Board
"""

from pathlib import Path

import pandas as pd
from dash import html, dcc, callback, Input, Output
import plotly.graph_objects as go
import numpy as np

from utils.overflow_simulator import (
    ProductBuffer, OverflowBoard, Zone, load_kanbans_from_csv, load_material_buffer_zones,
    load_or_create_material_fill_levels, get_sf2_orders_from_fg_orders,
    simulate_daily_consumption, load_sf2_buffers_from_material_zones,
    load_or_create_simulation_state, save_simulation_state, apply_pending_demand
)

def load_fg_buffers_from_material_zones():
    """Erstelle ProductBuffer für FG aus material_pufferzonen.csv."""
    material_zones = load_material_buffer_zones()
    fg_names = {'CT5', 'CT6', 'CT7', 'TT6', 'TT7', 'TT8'}
    products = {}
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
            daily_usage=0.0
        )
    return products


def create_replenishment_cards(cards_data):
    """Render Option 2A replenishment decisions as transparent cards."""
    if not cards_data:
        return html.Div("Keine Replenishment-Entscheidungen für diesen Tag.", style={'color': '#666', 'fontStyle': 'italic'})

    def _card(c):
        triggered = bool(c.get('trigger'))
        repl_qty = int(c.get('replenishment_qty', 0) or 0)
        header_bg = '#FFE0E0' if triggered else '#E8F5E9'
        header_fg = '#B00020' if triggered else '#2E7D32'

        return html.Div([
            html.Div(
                f"{c.get('material', '')}",
                style={'fontWeight': 'bold', 'color': header_fg}
            ),
            html.Div(
                f"NFP = OnHand({c.get('on_hand', 0)}) + OnOrder({c.get('on_order', 0)}) - Demand({c.get('demand', 0)}) = {c.get('net_flow', 0)}",
                style={'fontSize': '0.85rem', 'color': '#333', 'marginTop': '0.35rem'}
            ),
            html.Div(
                f"ToY={c.get('to_y', 0)} | ToG={c.get('to_g', 0)} | Trigger={'JA' if triggered else 'NEIN'}",
                style={'fontSize': '0.8rem', 'color': '#555', 'marginTop': '0.25rem'}
            ),
            html.Div(
                f"Replenishment = {repl_qty}",
                style={'fontSize': '0.95rem', 'fontWeight': 'bold', 'color': header_fg, 'marginTop': '0.35rem'}
            ),
        ], style={
            'backgroundColor': 'rgba(255,255,255,0.9)',
            'border': '1px solid #e0e0e0',
            'borderRadius': '8px',
            'padding': '0.75rem',
            'boxShadow': '0 1px 3px rgba(0,0,0,0.08)',
        })

    return html.Div(
        children=[_card(c) for c in cards_data],
        style={'display': 'grid', 'gridTemplateColumns': 'repeat(auto-fill, minmax(280px, 1fr))', 'gap': '0.75rem'}
    )


# ============================================================================
# Helper: Erstelle Kanban-Slot (Rechteckig für Zeilen-Ansicht)
# ============================================================================

def create_kanban_slot(filled: bool, zone: str, color: str, tooltip: str = None):
    """Erstelle einzelnen Kanban-Slot (Rechteckig für horizontale Ansicht)"""
    bg_color = color if filled else 'white'
    border_color = 'black' if filled else '#ccc'
    
    return html.Div(
        style={
            'width': '18px',         
            'height': '28px',        
            'backgroundColor': bg_color,
            'border': f'1px solid {border_color}',
            'margin': '2px',
            'display': 'inline-block',
            'borderRadius': '2px',
            'boxShadow': '1px 1px 2px rgba(0,0,0,0.2)' if filled else 'none',
            'backgroundImage': 'linear-gradient(45deg, #f0f0f0 25%, transparent 25%, transparent 50%, #f0f0f0 50%, #f0f0f0 75%, transparent 75%, transparent)' if not filled else 'none',
            'backgroundSize': '8px 8px' if not filled else 'auto'
        },
        title=tooltip or f"{'Belegt' if filled else 'Frei'} ({zone})"
    )


def _get_on_order_map_from_board(board_state, schedule_slots):
    """On-Order bleibt immer 0 (bewusst deaktiviert)."""
    return {}


def create_replenishment_cards(products, demand_map, material_zones, fill_levels, on_order_map):
    """Create simple replenishment cards based on Net Flow logic."""
    cards = []
    for material in products:
        zones = material_zones.get(material)
        if not zones:
            continue
        on_hand = int(fill_levels.get(material, 0))
        on_order = int(on_order_map.get(material, 0))
        demand = int(demand_map.get(material, 0))
        net_flow = on_hand + on_order - demand
        toy = int(zones['red'] + zones['yellow'])
        tog = int(zones['total'])
        trigger = net_flow <= toy
        repl_qty = max(0, tog - net_flow) if trigger else 0

        cards.append(html.Div([
            html.Div(material, style={
                'fontWeight': 'bold', 'fontSize': '0.95rem',
                'borderBottom': '1px solid #e6eef5', 'paddingBottom': '0.4rem'
            }),
            html.Div([
                html.Div("Net Flow:", style={'color': '#6a6a7a', 'fontSize': '0.8rem'}),
                html.Div(f"{on_hand} (On-Hand) + {on_order} (On-Order) - {demand} (Demand) = {net_flow}",
                         style={'fontWeight': 'bold', 'fontSize': '0.9rem'})
            ], style={'marginTop': '0.5rem'}),
            html.Div([
                html.Div("Trigger:", style={'color': '#6a6a7a', 'fontSize': '0.8rem'}),
                html.Div(f"Net Flow ({net_flow}) <= ToY ({toy})" if trigger else f"Net Flow ({net_flow}) > ToY ({toy})",
                         style={'fontWeight': 'bold', 'fontSize': '0.9rem',
                                'color': '#e67e22' if trigger else '#2ecc71'})
            ], style={'marginTop': '0.5rem'}),
            html.Div([
                html.Div("Replenishment Qty:", style={'color': '#6a6a7a', 'fontSize': '0.8rem'}),
                html.Div(f"ToG ({tog}) - Net Flow ({net_flow}) = {repl_qty}",
                         style={'fontWeight': 'bold', 'fontSize': '0.9rem',
                                'color': '#2ecc71' if repl_qty > 0 else '#999'})
            ], style={'marginTop': '0.5rem'})
        ], style={
            'backgroundColor': 'white',
            'borderRadius': '10px',
            'padding': '0.9rem',
            'boxShadow': '0 2px 6px rgba(0,0,0,0.08)',
            'border': '1px solid #e6eef5',
            'minWidth': '220px'
        }))

    if not cards:
        return html.Div("Keine Daten", style={'color': '#999', 'fontStyle': 'italic'})

    return html.Div(cards, style={
        'display': 'grid',
        'gridTemplateColumns': 'repeat(auto-fit, minmax(240px, 1fr))',
        'gap': '1rem'
    })

# ============================================================================
# Helper: Heijunka Shift-Board (Zeitplan) - SHIFT 1
# ============================================================================
def _get_shift_products(board_state):
    """Ermittle Produkte für Shift-Boards dynamisch aus dem Board-State."""
    if not board_state:
        return [], []
    normal = sorted([k for k, v in board_state.items() if not v.get('is_event', False)])
    events = [k for k, v in board_state.items() if v.get('is_event', False)]
    display = normal.copy()
    if events:
        display.append('E')
    return display, events

def _build_shift_slots(labels, start_index=0):
    slots = []
    pitch_index = start_index
    for label, is_break in labels:
        slots.append({'label': label, 'is_break': is_break, 'pitch_index': pitch_index if not is_break else None})
        if not is_break:
            pitch_index += 1
    return slots


def create_shift_board_Shift_1(schedule_data=None, board_state=None):
    """
    Erstellt das Shift-Board (Heijunka-Box) fürShift 1 (06:00 - 14:00, Pause 09:30 - 10:30).
    schedule_data: Dict mit Produkt -> Liste von Zeit-Slots (Integers 0-19), wo produziert wird.
    """

    slot_labels = [
        ("06:00", False), ("06:42", False), ("07:24", False), ("08:06", False), ("08:48", False),
        ("Pause 09:30-10:30", True),
        ("10:30", False), ("11:12", False), ("11:54", False), ("12:36", False), ("13:18", False)
    ]
    time_slots = _build_shift_slots(slot_labels, start_index=0)

    products, event_products = _get_shift_products(board_state or {})
    if not products:
        products = ["CT5", "CT6", "TT6", "TT7"]
        event_products = []

    product_colors = {
        "CT5": "#FFD700",
        "CT6": "#DAA520",
        "TT6": "#66cc66",
        "TT7": "#A9A9A9",
        "E": "#CC0000"
    }

    def slots_for_product(prod):
        if not schedule_data:
            return []
        if prod == "E":
            combined = []
            for ep in event_products:
                combined.extend(schedule_data.get(ep, []))
            return combined
        return schedule_data.get(prod, [])

    if board_state is None:
        board_state = {}

    header_row_1 = html.Tr([
        html.Th("Shift 1", colSpan=2, style={
            'backgroundColor': '#333', 'color': 'white', 'padding': '10px',
            'textAlign': 'left', 'fontSize': '1.2rem', 'border': '1px solid #555'
        }),
        *[html.Th(slot['label'], style={
            'backgroundColor': '#333', 'color': 'white', 'padding': '5px',
            'fontSize': '0.8rem', 'border': '1px solid #555', 'minWidth': '45px'
        }) for slot in time_slots]
    ])

    header_row_2 = html.Tr([
        html.Th("Pitch", style={'backgroundColor': '#333', 'color': 'white', 'fontSize': '0.7rem', 'border': '1px solid #555'}),
        html.Th("Alert", style={'backgroundColor': '#333', 'color': 'white', 'fontSize': '0.7rem', 'border': '1px solid #555'}),
        *[html.Th("", style={'backgroundColor': '#333', 'border': '1px solid #555', 'height': '5px'}) for _ in time_slots]
    ], style={'height': '20px'})

    rows = []

    for prod in products:
        prod_info = board_state.get(prod, {})
        current_zone = prod_info.get('current_zone', 'green') if prod_info else 'green'

        if current_zone == 'red':
            alert_color = "#FF0000"
        elif current_zone == 'yellow':
            alert_color = "#FFD700"
        else:
            alert_color = "#00B050"

        if prod == "E" or not prod_info:
            alert_color = "#d0d0d0"

        time_cells = []
        for slot in time_slots:
            slot_index = slot['pitch_index']
            prod_slots = slots_for_product(prod)
            slot_count = prod_slots.count(slot_index) if slot_index is not None else 0
            is_active = slot_count > 0
            is_break = slot['is_break']

            bg_style = {}
            content = ""

            if is_break:
                bg_style = {'backgroundColor': '#d0d0d0'}
            elif is_active:
                card_color = product_colors.get(prod, "#333")
                label = "2" if prod in ("CT5", "TT6") else ""
                label_color = "#111" if prod in ("CT5", "TT6") else "transparent"
                content = html.Div(label, style={
                    'width': '20px', 'height': '15px',
                    'backgroundColor': card_color,
                    'margin': 'auto',
                    'border': '1px solid #fff',
                    'clipPath': 'polygon(0 0, 100% 0, 100% 70%, 80% 100%, 0 100%)',
                    'color': label_color,
                    'fontSize': '0.75rem',
                    'fontWeight': 'bold',
                    'textAlign': 'center',
                    'lineHeight': '15px'
                })

            time_cells.append(html.Td(content, style={
                'border': '1px solid #333', 'textAlign': 'center', 'padding': '2px', **bg_style
            }))

        row = html.Tr([
            html.Td(html.Div([
                html.Span("", style={'fontSize': '0.7rem', 'transform': 'rotate(-90deg)', 'display': 'block', 'marginBottom': '5px', 'color': 'white'}),
                html.Span(prod, style={'fontSize': '1.2rem', 'fontWeight': 'bold'})
            ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center', 'height': '100%'}),
                style={'backgroundColor': '#808080', 'color': 'white', 'border': '1px solid #333', 'width': '30px'}),

            html.Td("", style={'backgroundColor': alert_color, 'border': '1px solid #333', 'width': '20px'}),
            *time_cells
        ], style={'height': '35px'})

        rows.append(row)

    return html.Table([
        html.Thead([header_row_1, header_row_2]),
        html.Tbody(rows)
    ], style={'borderCollapse': 'collapse', 'fontFamily': 'Arial, sans-serif', 'backgroundColor': 'white', 'boxShadow': '0 4px 8px rgba(0,0,0,0.1)'})


# ============================================================================
# Helper: Heijunka Shift-Board (Zeitplan) - SHIFT 2
# ============================================================================
def create_shift_board_Shift_2(schedule_data=None, board_state=None):
    """
    Erstellt das Shift-Board (Heijunka-Box) fürShift 2 (14:00 - 22:00, Pause 17:30 - 18:30).
    WICHTIG: Die Indizes im schedule_data laufen von 0 bis 19. Shift 2 zeigt 10 bis 19.
    """

    slot_labels = [
        ("14:00", False), ("14:42", False), ("15:24", False), ("16:06", False), ("16:48", False),
        ("Pause 17:30-18:30", True),
        ("18:30", False), ("19:12", False), ("19:54", False), ("20:36", False), ("21:18", False)
    ]
    time_slots = _build_shift_slots(slot_labels, start_index=10)

    products, event_products = _get_shift_products(board_state or {})
    if not products:
        products = ["CT5", "CT6", "TT6", "TT7"]
        event_products = []

    product_colors = {
        "CT5": "#FFD700",
        "CT6": "#DAA520",
        "TT6": "#66cc66",
        "TT7": "#A9A9A9",
        "E": "#CC0000"
    }

    def slots_for_product(prod):
        if not schedule_data:
            return []
        if prod == "E":
            combined = []
            for ep in event_products:
                combined.extend(schedule_data.get(ep, []))
            return combined
        return schedule_data.get(prod, [])

    if board_state is None:
        board_state = {}

    header_row_1 = html.Tr([
        html.Th("Shift 2", colSpan=2, style={
            'backgroundColor': '#333', 'color': 'white', 'padding': '10px',
            'textAlign': 'left', 'fontSize': '1.2rem', 'border': '1px solid #555'
        }),
        *[html.Th(slot['label'], style={
            'backgroundColor': '#333', 'color': 'white', 'padding': '5px',
            'fontSize': '0.8rem', 'border': '1px solid #555', 'minWidth': '45px'
        }) for slot in time_slots]
    ])

    header_row_2 = html.Tr([
        html.Th("Pitch", style={'backgroundColor': '#333', 'color': 'white', 'fontSize': '0.7rem', 'border': '1px solid #555'}),
        html.Th("Alert", style={'backgroundColor': '#333', 'color': 'white', 'fontSize': '0.7rem', 'border': '1px solid #555'}),
        *[html.Th("", style={'backgroundColor': '#333', 'border': '1px solid #555', 'height': '5px'}) for _ in time_slots]
    ], style={'height': '20px'})

    rows = []

    for prod in products:
        prod_info = board_state.get(prod, {})
        current_zone = prod_info.get('current_zone', 'green') if prod_info else 'green'

        if current_zone == 'red':
            alert_color = "#FF0000"
        elif current_zone == 'yellow':
            alert_color = "#FFD700"
        else:
            alert_color = "#00B050"

        if prod == "E" or not prod_info:
            alert_color = "#d0d0d0"

        time_cells = []
        for slot in time_slots:
            slot_index = slot['pitch_index']
            prod_slots = slots_for_product(prod)
            slot_count = prod_slots.count(slot_index) if slot_index is not None else 0
            is_active = slot_count > 0
            is_break = slot['is_break']

            bg_style = {}
            content = ""

            if is_break:
                bg_style = {'backgroundColor': '#d0d0d0'}
            elif is_active:
                card_color = product_colors.get(prod, "#333")
                label = str(slot_count) if slot_count > 1 else ""
                content = html.Div(label, style={
                    'width': '20px', 'height': '15px',
                    'backgroundColor': card_color,
                    'margin': 'auto',
                    'border': '1px solid #fff',
                    'clipPath': 'polygon(0 0, 100% 0, 100% 70%, 80% 100%, 0 100%)',
                    'color': '#111',
                    'fontSize': '0.75rem',
                    'fontWeight': 'bold',
                    'textAlign': 'center',
                    'lineHeight': '15px'
                })

            time_cells.append(html.Td(content, style={
                'border': '1px solid #333', 'textAlign': 'center', 'padding': '2px', **bg_style
            }))

        row = html.Tr([
            html.Td(html.Div([
                html.Span("", style={'fontSize': '0.7rem', 'transform': 'rotate(-90deg)', 'display': 'block', 'marginBottom': '5px', 'color': 'white'}),
                html.Span(prod, style={'fontSize': '1.2rem', 'fontWeight': 'bold'})
            ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center', 'height': '100%'}),
                style={'backgroundColor': '#808080', 'color': 'white', 'border': '1px solid #333', 'width': '30px'}),

            html.Td("", style={'backgroundColor': alert_color, 'border': '1px solid #333', 'width': '20px'}),
            *time_cells
        ], style={'height': '35px'})

        rows.append(row)

    return html.Table([
        html.Thead([header_row_1, header_row_2]),
        html.Tbody(rows)
    ], style={'borderCollapse': 'collapse', 'fontFamily': 'Arial, sans-serif', 'backgroundColor': 'white', 'boxShadow': '0 4px 8px rgba(0,0,0,0.1)'})


# ============================================================================
# Helper: Heijunka Shift-Board (Zeitplan) - LOOP A (SF2) - Pitch 32min
# ============================================================================
def create_shift_board_loop_a_shift_1(schedule_data=None, board_state=None):
    """Shift-Board für Loop A (SF2) Frühschicht mit Pitch=32min.

    Struktur:
    - 06:00–08:40: Pitch 1–5
    - 08:40–09:40: Pause
    - 09:40–14:00: Pitch 6–13 (letzter Pitch bis 14:00 gestreckt, Puffer nicht separat)

    schedule_data: Dict Produkt -> Liste von Slot-Indizes (0..25) über den ganzen Tag.
    """
    columns = [
        ("06:00", 0), ("06:32", 1), ("07:04", 2), ("07:36", 3), ("08:08", 4),
        ("Pause 08:40–09:40", None),
        ("09:40", 5), ("10:12", 6), ("10:44", 7), ("11:16", 8), ("11:48", 9),
        ("12:20", 10), ("12:52", 11), ("13:24", 12),
    ]
    return _create_shift_board_generic(
        title="Shift 1",
        columns=columns,
        schedule_data=schedule_data,
        board_state=board_state,
        slot_index_offset=0,
    )


def create_shift_board_loop_a_shift_2(schedule_data=None, board_state=None):
    """Shift-Board für Loop A (SF2) Spätschicht mit Pitch=32min.

    Struktur:
    - 14:00–16:40: Pitch 1–5
    - 16:40–17:40: Pause
    - 17:40–22:00: Pitch 6–13 (letzter Pitch bis 22:00 gestreckt, Puffer nicht separat)

    schedule_data: Dict Produkt -> Liste von Slot-Indizes (0..25) über den ganzen Tag.
    """
    columns = [
        ("14:00", 13), ("14:32", 14), ("15:04", 15), ("15:36", 16), ("16:08", 17),
        ("Pause 16:40–17:40", None),
        ("17:40", 18), ("18:12", 19), ("18:44", 20), ("19:16", 21), ("19:48", 22),
        ("20:20", 23), ("20:52", 24), ("21:24", 25),
    ]
    return _create_shift_board_generic(
        title="Shift 2",
        columns=columns,
        schedule_data=schedule_data,
        board_state=board_state,
        slot_index_offset=0,
    )


# ============================================================================
# Helper: Baue das gesamte Board-Grid (Header + Zeilen)
# ============================================================================

def create_board_grid(board_state):
    """Erstellt die komplette Grid-Struktur für das Overflow Board"""
    grid_style = {
        'display': 'grid',
        'gridTemplateColumns': '110px 1.2fr 1.5fr 4fr',
        'gap': '6px',
        'backgroundColor': '#2b2b2b',
        'padding': '6px',
        'borderRadius': '8px',
        'fontFamily': 'Arial, sans-serif',
        'overflowX': 'auto'
    }
    
    children = []

    # --- HEADER ---
    children.append(html.Div(
        html.Div(
            ["Overflow-", html.Br(), "Board"],
            style={'fontWeight': 'bold', 'textAlign': 'center', 'letterSpacing': '0.5px'}
        ),
        style={
            'gridRow': '1 / span 2',
            'gridColumn': '1',
            'backgroundColor': '#1f1f1f',
            'color': 'white',
            'display': 'flex',
            'alignItems': 'center',
            'justifyContent': 'center',
            'padding': '8px 6px',
            'fontSize': '0.9rem',
            'borderRadius': '6px',
            'border': '1px solid #444'
        }
    ))

    children.append(html.Div(
        "Make decision",
        style={'gridRow': '1', 'gridColumn': '2 / span 3', 'backgroundColor': '#1f1f1f', 'color': 'white', 'textAlign': 'center', 'padding': '4px', 'fontWeight': 'bold', 'fontSize': '0.9rem', 'borderRadius': '6px', 'border': '1px solid #444'}
    ))

    headers = [("No", '#00B050'), ("Can", '#FFD700'), ("Yes", '#FF0000')]
    for idx, (text, bg) in enumerate(headers):
        children.append(html.Div(text, style={'gridRow': '2', 'gridColumn': str(idx + 2), 'backgroundColor': bg, 'color': 'black' if text == "Can" else 'white', 'fontWeight': 'bold', 'textAlign': 'center', 'padding': '4px'}))

    # --- ZEILEN ---
    # Filtere Events und Produkte
    normal_products = sorted([k for k in board_state.keys() if not board_state[k].get('is_event', False)])
    event_products = [k for k in board_state.keys() if board_state[k].get('is_event', False)]
    
    def add_row(name, data, is_summary_row=False):
        bg_label = '#8a8a8a' if is_summary_row else '#e5e5e5'
        total_capacity = int(data.get('green_cap', 0) or 0) + int(data.get('yellow_cap', 0) or 0) + int(data.get('red_cap', 0) or 0)
        total_current = int(data.get('green_current', 0) or 0) + int(data.get('yellow_current', 0) or 0) + int(data.get('red_current', 0) or 0)
        children.append(html.Div(
            name,
            style={
                'backgroundColor': bg_label,
                'display': 'flex',
                'alignItems': 'center',
                'justifyContent': 'center',
                'fontWeight': 'bold',
                'fontSize': '1rem',
                'color': 'white' if is_summary_row else '#333',
                'padding': '8px',
                'textAlign': 'center',
                'borderRadius': '4px'
            }
        ))
        
        zones = [('green', '#00B050'), ('yellow', '#FFD700'), ('red', '#FF0000')]
        for zone_name, color in zones:
            cap_key = f"{zone_name}_cap"
            curr_key = f"{zone_name}_current"
            capacity = data.get(cap_key, 0)
            current = data.get(curr_key, 0)
            
            slots = []
            for i in range(capacity):
                is_filled = i < current
                slot_color = color
                if is_summary_row and zone_name == 'red': slot_color = '#b30000'
                tooltip = f"{name}: {total_current}/{total_capacity} gesamt | {zone_name} {current}/{capacity}"
                slots.append(create_kanban_slot(is_filled, zone_name, slot_color, tooltip))
            
            children.append(html.Div(slots, style={'backgroundColor': 'white', 'display': 'flex', 'flexWrap': 'wrap', 'alignContent': 'center', 'padding': '4px', 'minHeight': '40px'}))

    for name in normal_products:
        add_row(name, board_state[name])
        
    if event_products:
        e_data = {
            'green_cap': sum(board_state[p]['green_cap'] for p in event_products),
            'green_current': sum(board_state[p]['green_current'] for p in event_products),
            'yellow_cap': sum(board_state[p]['yellow_cap'] for p in event_products),
            'yellow_current': sum(board_state[p]['yellow_current'] for p in event_products),
            'red_cap': sum(board_state[p]['red_cap'] for p in event_products),
            'red_current': sum(board_state[p]['red_current'] for p in event_products),
        }
        add_row("E", e_data, is_summary_row=True)

    return html.Div(children, style=grid_style)


def load_max_kanbans_per_pitch(loop_name: str) -> dict:
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
        name = str(row.get('Produkt', '')).strip()
        if not name or name.lower() == 'summe':
            continue
        val = row.get('Maximum number of Kanbans per Pitch')
        try:
            max_map[name] = int(float(val))
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

# ============================================================================
# Helper: Kanban-Statusboards & Priorisierung
# ============================================================================

def create_kanban_status_boards(board_state: dict):
    """Kanban-Statusboards mit Anzahl pro Zone"""
    status_cards = []
    for prod_name in sorted(board_state.keys()):
        prod_data = board_state[prod_name]
        event_marker = " 🎯" if prod_data.get('is_event', False) else ""
        card = html.Div([
            html.Div(f"{prod_name}{event_marker}", style={'fontSize': '0.85rem', 'fontWeight': 'bold', 'marginBottom': '0.5rem', 'color': '#2c3e50', 'borderBottom': '1px solid #e0e0e0', 'paddingBottom': '0.5rem'}),
            html.Div([
                html.Div([html.Span("Rot:", style={'fontSize': '0.75rem', 'color': '#666', 'marginRight': '0.3rem'}), 
                          html.Span(str(prod_data['red_current']), style={'backgroundColor': '#FF6B6B', 'color': 'white', 'padding': '0.2rem 0.4rem', 'borderRadius': '3px', 'fontSize': '0.8rem', 'fontWeight': 'bold'})], 
                        style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '0.3rem'}),
                html.Div([html.Span("Gelb:", style={'fontSize': '0.75rem', 'color': '#666', 'marginRight': '0.3rem'}), 
                          html.Span(str(prod_data['yellow_current']), style={'backgroundColor': '#FFD700', 'color': '#333', 'padding': '0.2rem 0.4rem', 'borderRadius': '3px', 'fontSize': '0.8rem', 'fontWeight': 'bold'})], 
                        style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '0.3rem'}),
                html.Div([html.Span("Grün:", style={'fontSize': '0.75rem', 'color': '#666', 'marginRight': '0.3rem'}), 
                          html.Span(str(prod_data['green_current']), style={'backgroundColor': '#51CF66', 'color': 'white', 'padding': '0.2rem 0.4rem', 'borderRadius': '3px', 'fontSize': '0.8rem', 'fontWeight': 'bold'})], 
                        style={'display': 'flex', 'alignItems': 'center'})
            ], style={'marginBottom': '0.5rem'}),
            html.Div(f"∑ {prod_data['current_total']}", style={'fontSize': '0.8rem', 'color': '#5A9FBF', 'fontWeight': 'bold', 'textAlign': 'center', 'paddingTop': '0.4rem', 'borderTop': '1px solid #e0e0e0'})
        ], style={'backgroundColor': 'white', 'padding': '0.7rem', 'borderRadius': '5px', 'boxShadow': '0 1px 3px rgba(0,0,0,0.08)', 'border': '1px solid #e0e0e0'})
        status_cards.append(card)
    
    return html.Div(status_cards, style={'display': 'grid', 'gridTemplateColumns': 'repeat(auto-fill, minmax(130px, 1fr))', 'gap': '0.75rem', 'padding': '1rem', 'backgroundColor': '#f8f9fa', 'borderRadius': '6px'})


def create_priority_ranking_table(board_state: dict):
    """Priorisierungs-Tabelle"""
    ranking_data = []
    for prod_name, prod_data in board_state.items():
        ranking_data.append({
            'Produkt': prod_name, 
            'Grün': prod_data['green_current'], 'Gelb': prod_data['yellow_current'], 'Rot': prod_data['red_current'], 
            'Gesamt': prod_data['current_total'], 'Kapazität': prod_data['total_capacity'], 
            'Auslastung': f"{prod_data['fill_percentage']*100:.0f}%", 
            'Zone': prod_data['current_zone'].upper(), 
            'Event': '✓' if prod_data.get('is_event', False) else ''
        })
    
    zone_order = {'RED': 0, 'YELLOW': 1, 'GREEN': 2}
    ranking_data.sort(key=lambda x: (zone_order.get(x['Zone'], 3), -x['Gesamt']))
    
    zone_colors = {'RED': '#FF6B6B', 'YELLOW': '#FFD700', 'GREEN': '#51CF66'}
    
    header = html.Tr(
        [html.Th(col, style={'padding': '0.6rem 0.5rem', 'textAlign': 'left', 'fontWeight': 'bold', 'fontSize': '0.85rem', 'borderBottom': '2px solid #5A9FBF'}) 
         for col in ['Produkt', 'Grün', 'Gelb', 'Rot', 'Gesamt', 'Kapazität', 'Auslastung', 'Zone', 'Event']], 
        style={'backgroundColor': '#5A9FBF', 'color': 'white'}
    )
    
    rows = []
    for i, row in enumerate(ranking_data):
        bg_color = '#f8f9fa' if i % 2 == 0 else 'white'
        zone_color = zone_colors.get(row['Zone'], '#999')
        rows.append(html.Tr([
            html.Td(row['Produkt'], style={'padding': '0.5rem', 'fontSize': '0.85rem'}),
            html.Td(str(row['Grün']), style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'}),
            html.Td(str(row['Gelb']), style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'}),
            html.Td(str(row['Rot']), style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'}),
            html.Td(str(row['Gesamt']), style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem', 'fontWeight': 'bold'}),
            html.Td(str(row['Kapazität']), style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem', 'color': '#999'}),
            html.Td(row['Auslastung'], style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem', 'fontWeight': 'bold'}),
            html.Td(html.Span(row['Zone'], style={'backgroundColor': zone_color, 'color': 'white', 'padding': '0.25rem 0.5rem', 'borderRadius': '3px', 'fontSize': '0.75rem', 'fontWeight': 'bold'}), style={'padding': '0.5rem', 'textAlign': 'center'}),
            html.Td(row['Event'], style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'})
        ], style={'backgroundColor': bg_color, 'borderBottom': '1px solid #e0e0e0'}))
    
    return html.Table([header] + rows, style={'width': '100%', 'borderCollapse': 'collapse', 'borderRadius': '6px', 'overflow': 'hidden', 'boxShadow': '0 2px 6px rgba(0,0,0,0.08)', 'fontSize': '0.9rem'})


def create_replenishment_cards(cards: list, title: str):
    """Zeigt Replenishment-Entscheidungen als transparente Karten."""
    if not cards:
        return html.Div([
            html.H4(title, style={'marginBottom': '0.6rem', 'color': '#2c3e50'}),
            html.Div("Keine Replenishment Orders für heute.", style={'color': '#888'})
        ])

    def fmt(v):
        try:
            return f"{int(v)}"
        except Exception:
            return str(v)

    card_nodes = []
    for item in cards:
        trigger = bool(item.get('trigger'))
        accent = '#FF6B6B' if trigger else '#51CF66'

        on_hand = item.get('on_hand', 0)
        on_order = item.get('on_order', 0)
        demand = item.get('demand', 0)
        net_flow = item.get('net_flow', 0)
        toy = item.get('to_y', 0)
        tog = item.get('to_g', 0)
        repl_qty = item.get('replenishment_qty', 0)

        trigger_text = "JA" if trigger else "NEIN"
        decision_text = f"Net Flow ({fmt(net_flow)}) <= ToY ({fmt(toy)})" if trigger else f"Net Flow ({fmt(net_flow)}) > ToY ({fmt(toy)})"
        card_nodes.append(
            html.Div([
                html.Div([
                    html.Div(item.get('material', ''), style={'fontWeight': 'bold'}),
                    html.Div(
                        f"Trigger: {trigger_text}",
                        style={
                            'fontSize': '0.75rem',
                            'fontWeight': 'bold',
                            'padding': '0.15rem 0.45rem',
                            'borderRadius': '999px',
                            'border': f'1px solid {accent}',
                            'color': accent,
                            'backgroundColor': 'rgba(255,255,255,0.6)'
                        }
                    )
                ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center', 'marginBottom': '0.45rem'}),

                html.Div([
                    html.Div("Net Flow (NFP)", style={'fontSize': '0.8rem', 'fontWeight': 'bold', 'color': '#2c3e50', 'marginBottom': '0.15rem'}),
                    html.Div(
                        f"NFP = OnHand({fmt(on_hand)}) + OnOrder({fmt(on_order)}) - Demand({fmt(demand)}) = {fmt(net_flow)}",
                        style={'fontSize': '0.82rem', 'color': '#34495e'}
                    ),
                ], style={'marginBottom': '0.5rem'}),

                html.Div([
                    html.Div("Decision", style={'fontSize': '0.8rem', 'fontWeight': 'bold', 'color': '#2c3e50', 'marginBottom': '0.15rem'}),
                    html.Div(
                        decision_text,
                        style={'fontSize': '0.82rem', 'color': '#34495e'}
                    ),
                ], style={'marginBottom': '0.5rem'}),

                html.Div([
                    html.Div("Replenishment Qty", style={'fontSize': '0.8rem', 'fontWeight': 'bold', 'color': '#2c3e50', 'marginBottom': '0.15rem'}),
                    html.Div(
                        f"Repl = {'max(0, ' if trigger else ''}ToG({fmt(tog)}) - NFP({fmt(net_flow)}){')' if trigger else ''} = {fmt(repl_qty)}",
                        style={'fontSize': '0.82rem', 'color': '#34495e', 'fontWeight': 'bold' if trigger else 'normal'}
                    ),
                    html.Div(
                        f"ToY={fmt(toy)} | ToG={fmt(tog)}",
                        style={'fontSize': '0.78rem', 'color': '#7f8c8d', 'marginTop': '0.25rem'}
                    ),
                ]),
            ], style={
                'backgroundColor': 'rgba(255,255,255,0.7)',
                'border': f'2px solid {accent}',
                'borderRadius': '10px',
                'padding': '0.75rem',
                'boxShadow': '0 2px 6px rgba(0,0,0,0.08)'
            })
        )

    return html.Div([
        html.H4(title, style={'marginBottom': '0.6rem', 'color': '#2c3e50'}),
        html.Div(card_nodes, style={'display': 'grid', 'gridTemplateColumns': 'repeat(auto-fill, minmax(180px, 1fr))', 'gap': '0.75rem'})
    ])

# ============================================================================
# Helper: Produktionsplan auf Zeitslots verteilen (Heijunka-Box)
# ============================================================================
def distribute_schedule_to_shift_slots(schedule: dict, all_products: dict, slots_per_day: int = 32) -> dict:
    """
    Verteilt einen Produktionsplan (Produkt -> Menge) auf diskrete Zeitslots.
    Einfacher Round-Robin, um Produkte möglichst zu streuen.
    """
    slot_plan = {name: [] for name in all_products.keys()}
    remaining = {p: qty for p, qty in schedule.items() if qty > 0}
    if not remaining:
        return slot_plan

    order = sorted(remaining.keys())
    slot_index = 0
    while slot_index < slots_per_day and any(qty > 0 for qty in remaining.values()):
        for prod in order:
            if remaining.get(prod, 0) <= 0:
                continue
            slot_plan[prod].append(slot_index)
            remaining[prod] -= 1
            slot_index += 1
            if slot_index >= slots_per_day:
                break

    return slot_plan

# ============================================================================
# Helper: Prioritaetsbasierter Tagesplan (fuellt bis zu slots_per_day)
# ============================================================================
def _normalize_mix_weights(board: OverflowBoard, mix_weights: dict | None) -> dict | None:
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
    mix_weights: dict | None = None,
) -> dict:
    """Heijunka-Slot-Planung über den Tag.

    Regeln (vereinfacht, pruefungsfest):
    - Zonen-Prioritaet: Rot -> Gelb -> Gruen (immer erst hoechste vorhandene Zone abarbeiten)
    - Innerhalb Zone: Penetration (rot/gelb/gruen), ABC/XYZ nur als Tie-Breaker
    - CT5-Sonderregel: pro Slot werden 2 Kanbans geplant (auch wenn nur 1 vorhanden ist)
    - Setup wird hier nicht modelliert; Wechsel werden nur als Tie-Breaker reduziert.

    Hinweis: Wir entfernen Kanbans aus dem Board, um den geplanten Output sichtbar zu machen.
    """
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

    def mix_deficit(name: str, pool: list, slot_idx: int) -> float | None:
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
    mix_weights: dict | None = None,
) -> dict:
    """
    Priorisiert Produkte mit Replenishment Qty > 0 und faellt danach mit Standard-Prioritaet auf.
    """
    slot_plan = {name: [] for name in board.products.keys()}
    max_per_pitch = max_per_pitch or {}
    repl_remaining = dict(repl_qty_map or {})
    mix_weights = _normalize_mix_weights(board, mix_weights)
    produced_slots = {name: 0 for name in board.products.keys()} if mix_weights else {}
    if not repl_remaining:
        return build_slot_schedule_full_day(board, slots_per_day, max_per_pitch, mix_weights)

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

    def mix_deficit(name: str, pool: list, slot_idx: int) -> float | None:
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


def _create_shift_board_generic(*, title: str, columns: list, schedule_data=None, board_state=None, slot_index_offset: int = 0):
    """Generischer Renderer für Shift-Boards.

    columns: Liste von Tupeln (label, slot_index|None). None bedeutet Pause-Spalte.
    schedule_data: Dict Produkt -> Liste Slot-Indizes.
    """
    time_labels = [label for (label, _) in columns]

    products, event_products = _get_shift_products(board_state or {})
    if not products:
        products = ["CT5", "CT6", "TT6", "TT7"]
        event_products = []

    product_colors = {
        "CT5": "#FFD700",
        "CT6": "#DAA520",
        "CT7": "#C9B037",
        "TT6": "#66cc66",
        "TT7": "#A9A9A9",
        "TT8": "#666666",
        "E": "#CC0000",
    }

    def slots_for_product(prod):
        if not schedule_data:
            return []
        if prod == "E":
            combined = []
            for ep in event_products:
                combined.extend(schedule_data.get(ep, []))
            return sorted(set(combined))
        return schedule_data.get(prod, [])

    if board_state is None:
        board_state = {}

    header_row_1 = html.Tr([
        html.Th(title, colSpan=2, style={
            'backgroundColor': '#333', 'color': 'white', 'padding': '10px',
            'textAlign': 'left', 'fontSize': '1.2rem', 'border': '1px solid #555'
        }),
        *[html.Th(time, style={
            'backgroundColor': '#333', 'color': 'white', 'padding': '5px',
            'fontSize': '0.8rem', 'border': '1px solid #555', 'minWidth': '45px'
        }) for time in time_labels]
    ])

    header_row_2 = html.Tr([
        html.Th("Pitch", style={'backgroundColor': '#333', 'color': 'white', 'fontSize': '0.7rem', 'border': '1px solid #555'}),
        html.Th("Alert", style={'backgroundColor': '#333', 'color': 'white', 'fontSize': '0.7rem', 'border': '1px solid #555'}),
        *[html.Th("", style={'backgroundColor': '#333', 'border': '1px solid #555', 'height': '5px'}) for _ in time_labels]
    ], style={'height': '20px'})

    rows = []

    for prod in products:
        prod_info = board_state.get(prod, {})
        current_zone = prod_info.get('current_zone', 'green') if prod_info else 'green'

        if current_zone == 'red':
            alert_color = "#FF0000"
        elif current_zone == 'yellow':
            alert_color = "#FFD700"
        else:
            alert_color = "#00B050"

        if prod == "E" or not prod_info:
            alert_color = "#d0d0d0"

        time_cells = []
        prod_slots = slots_for_product(prod)
        for (label, slot_index) in columns:
            is_break = slot_index is None
            is_active = (slot_index is not None) and ((slot_index + slot_index_offset) in prod_slots)

            bg_style = {}
            content = ""

            if is_break:
                bg_style = {'backgroundColor': '#d0d0d0'}
            elif is_active:
                card_color = product_colors.get(prod, "#333")
                content = html.Div(style={
                    'width': '20px', 'height': '15px',
                    'backgroundColor': card_color,
                    'margin': 'auto',
                    'border': '1px solid #fff',
                    'clipPath': 'polygon(0 0, 100% 0, 100% 70%, 80% 100%, 0 100%)'
                })

            time_cells.append(html.Td(content, style={
                'border': '1px solid #333', 'textAlign': 'center', 'padding': '2px', **bg_style
            }))

        row = html.Tr([
            html.Td(html.Div([
                html.Span("", style={'fontSize': '0.7rem', 'transform': 'rotate(-90deg)', 'display': 'block', 'marginBottom': '5px', 'color': 'white'}),
                html.Span(prod, style={'fontSize': '1.2rem', 'fontWeight': 'bold'})
            ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center', 'height': '100%'}),
                style={'backgroundColor': '#808080', 'color': 'white', 'border': '1px solid #333', 'width': '30px'}),

            html.Td("", style={'backgroundColor': alert_color, 'border': '1px solid #333', 'width': '20px'}),
            *time_cells
        ], style={'height': '35px'})

        rows.append(row)

    return html.Table([
        html.Thead([header_row_1, header_row_2]),
        html.Tbody(rows)
    ], style={'borderCollapse': 'collapse', 'fontFamily': 'Arial, sans-serif', 'backgroundColor': 'white', 'boxShadow': '0 4px 8px rgba(0,0,0,0.1)'})

# ============================================================================
# Logik: Zustand wiederherstellen
# ============================================================================

def sync_board_to_state(fresh_board, state_data):

    if not state_data:
        return fresh_board
    
    consumption = {}
    for prod_name, prod_obj in fresh_board.products.items():
        if prod_name in state_data:
            # Wie viel ist aktuell da?
            target_qty = state_data[prod_name].get('current_total', 0)
            
            # Wie viel wäre voll? (Kapazität berechnen)
            # Fallback, falls total_capacity fehlt
            if hasattr(prod_obj, 'total_capacity'):
                max_cap = prod_obj.total_capacity
            else:
                max_cap = getattr(prod_obj, 'green_capacity', 0) + getattr(prod_obj, 'yellow_capacity', 0) + getattr(prod_obj, 'red_capacity', 0)
                
            start_qty = getattr(prod_obj, 'current_quantity', max_cap)
            
            # Differenz = Was verbraucht wurde
            if start_qty > target_qty:
                consumption[prod_name] = int(start_qty - target_qty)
                
    # Wende den "Verbrauch" an, damit das Board den korrekten Leer-Zustand hat
    if consumption:
        fresh_board = simulate_daily_consumption(fresh_board, consumption)
        
    return fresh_board


# ============================================================================
# Callback
# ============================================================================

@callback(
    [Output('overflow-board-state', 'data'),
     Output('overflow-schedule-b', 'data'),
     Output('overflow-board-container', 'children'),
     Output('kanban-status-container', 'children'),
     Output('priority-table-container', 'children'),
     Output('shift-1-container', 'children'),
     Output('shift-2-container', 'children'),
     Output('replenishment-cards-container', 'children')],
    [Input('btn-produce', 'n_clicks'),
     Input('global-simulation-state', 'data')],
    prevent_initial_call=False
)
def update_board(n_produce, global_state):
    from dash import callback_context
    ctx = callback_context

    def build_board_from_state(state_dict, product_map, use_total_fill=False):
        """Rekonstruiere Board aus bestehendem State."""
        reconstructed = OverflowBoard(products=product_map)
        if not state_dict:
            return reconstructed
        for prod, data in state_dict.items():
            if prod not in reconstructed.products:
                continue
            if use_total_fill:
                total = int(data.get('current_total', 0))
                reconstructed.add_kanban(prod, total)
            else:
                green = int(data.get('green_current', 0))
                yellow = int(data.get('yellow_current', 0))
                red = int(data.get('red_current', 0))
                reconstructed.current_kanbans[prod] = (
                    [Zone.GREEN] * green + [Zone.YELLOW] * yellow + [Zone.RED] * red
                )
        return reconstructed

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

    products_b = load_fg_buffers_from_material_zones()
    state_b = global_state.get('board') if isinstance(global_state, dict) else None
    board = build_board_from_state(state_b, products_b, use_total_fill=True)

    repl_cards = []
    if isinstance(global_state, dict):
        repl_cards = global_state.get('replenishment_cards', []) or []

    schedule_slots = {}
    daily_orders = {}
    if global_state and isinstance(global_state, dict):
        daily_orders = global_state.get('daily_orders', {})

    if not trigger_id:
        board_state = board.to_dict()
    elif trigger_id == 'btn-produce':
        sim_state = load_or_create_simulation_state()
        apply_pending_demand(sim_state)
        plan_day = None
        if isinstance(global_state, dict):
            plan_day = global_state.get('day')
        if plan_day is None:
            plan_day = sim_state.current_day
        sim_state.heijunka_planned_day_b = int(plan_day)
        save_simulation_state(sim_state)
        material_zones = load_material_buffer_zones()
        fill_levels = load_or_create_material_fill_levels()
        repl_qty_map = {}
        for prod in products_b.keys():
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
        schedule_slots = build_slot_schedule_full_day_with_replenishment(
            board,
            repl_qty_map,
            slots_per_day=20,
            max_per_pitch=load_max_kanbans_per_pitch('B'),
            mix_weights=daily_orders,
        )
        board_state = board.to_dict()
    elif trigger_id == 'global-simulation-state':
        board_state = board.to_dict()
    else:
        board_state = board.to_dict()

    board_grid = create_board_grid(board_state)
    status_board = create_kanban_status_boards(board_state)
    prio_table = create_priority_ranking_table(board_state)

    shift_1 = create_shift_board_Shift_1(schedule_slots, board_state)
    shift_2 = create_shift_board_Shift_2(schedule_slots, board_state)

    cards_container = create_replenishment_cards(repl_cards, title='Replenishment Orders (Loop B)')
    return board_state, schedule_slots, board_grid, status_board, prio_table, shift_1, shift_2, cards_container






@callback(
    [Output('overflow-board-state-a', 'data'),
     Output('overflow-schedule-a', 'data'),
     Output('overflow-board-container-a', 'children'),
     Output('kanban-status-container-a', 'children'),
     Output('priority-table-container-a', 'children'),
     Output('shift-1-container-a', 'children'),
     Output('shift-2-container-a', 'children'),
     Output('replenishment-cards-container-a', 'children')],
    [Input('btn-produce-a', 'n_clicks'),
     Input('global-simulation-state', 'data')],
    prevent_initial_call=False
)
def update_board_a(n_produce, global_state):
    from dash import callback_context
    ctx = callback_context

    def build_board_from_state(state_dict, product_map):
        reconstructed = OverflowBoard(products=product_map)
        if not state_dict:
            return reconstructed
        for prod, data in state_dict.items():
            if prod not in reconstructed.products:
                continue
            green = int(data.get('green_current', 0))
            yellow = int(data.get('yellow_current', 0))
            red = int(data.get('red_current', 0))
            reconstructed.current_kanbans[prod] = (
                [Zone.GREEN] * green + [Zone.YELLOW] * yellow + [Zone.RED] * red
            )
        return reconstructed

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

    products_a = load_sf2_buffers_from_material_zones()
    state_a = global_state.get('board_a') if isinstance(global_state, dict) else None
    board = build_board_from_state(state_a, products_a)

    repl_cards = []
    if isinstance(global_state, dict):
        repl_cards = global_state.get('replenishment_cards_a', []) or []

    schedule_slots = {}
    daily_orders = {}
    if global_state and isinstance(global_state, dict):
        daily_orders = global_state.get('daily_orders', {})
    sf2_orders = get_sf2_orders_from_fg_orders(daily_orders)

    if not trigger_id:
        board_state = board.to_dict()
    elif trigger_id == 'btn-produce-a':
        sim_state = load_or_create_simulation_state()
        plan_day = None
        if isinstance(global_state, dict):
            plan_day = global_state.get('day')
        if plan_day is None:
            plan_day = sim_state.current_day
        sim_state.heijunka_planned_day_a = int(plan_day)
        save_simulation_state(sim_state)
        # Loop A: Pitch=32min => 13 Slots pro Schicht => 26 Slots pro Tag
        schedule_slots = build_slot_schedule_full_day(
            board,
            slots_per_day=26,
            mix_weights=sf2_orders,
        )
        board_state = board.to_dict()
    elif trigger_id == 'global-simulation-state':
        board_state = board.to_dict()
    else:
        board_state = board.to_dict()

    board_grid = create_board_grid(board_state)
    status_board = create_kanban_status_boards(board_state)
    prio_table = create_priority_ranking_table(board_state)

    shift_1 = create_shift_board_loop_a_shift_1(schedule_slots, board_state)
    shift_2 = create_shift_board_loop_a_shift_2(schedule_slots, board_state)

    cards_container = create_replenishment_cards(repl_cards, title='Replenishment Orders (Loop A)')
    return board_state, schedule_slots, board_grid, status_board, prio_table, shift_1, shift_2, cards_container

# ============================================================================
# Main Layout
# ============================================================================

def layout_loop_b():
    """Overflow-Board Layout fürLoop B (FG)"""
    try:
        products_b = load_fg_buffers_from_material_zones()
        board_b = OverflowBoard(products=products_b)
        initial_state = board_b.to_dict()
    except:
        initial_state = {}

    return html.Div([
        dcc.Store(id='overflow-board-state', data=initial_state),
        dcc.Store(id='overflow-schedule-b', data={}),

        html.H3('Loop B (FG) - Overflow-Board / Heijunka-Planung', style={'marginBottom': '1rem', 'color': '#2c3e50'}),
        html.Div([
            html.H4('Replenishment Orders', style={'marginBottom': '0.75rem', 'color': '#1a1a2e', 'fontSize': '1rem'}),
            html.Div(id='replenishment-cards-b')
        ], style={'marginBottom': '1.5rem'}),

        html.Div([
            html.Button('Planen (Loop B)', id='btn-produce', style={'padding': '0.5rem 1rem', 'backgroundColor': '#51CF66', 'color': 'white', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer'})
        ], style={'marginBottom': '1.5rem'}),

        html.Div(id='replenishment-cards-container', children=[
            create_replenishment_cards([], title='Replenishment Orders (Loop B)')
        ], style={'marginBottom': '1rem'}),

        html.Div(id='overflow-board-container', children=[
            create_board_grid(initial_state)
        ], style={'marginBottom': '2rem'}),

        html.Div([
        html.H4('Shift Plan 06:00 - 14:00 (Pause 08:40-09:40)', style={'marginBottom': '1rem', 'color': '#2c3e50', 'fontSize': '1rem'}),
            html.Div(id='shift-1-container', children=[create_shift_board_Shift_1(None, initial_state)])
        ]),

        html.Div([
        html.H4('Shift Plan 14:00 - 22:00 (Pause 16:40-17:40)', style={'marginBottom': '1rem', 'color': '#2c3e50', 'fontSize': '1rem'}),
            html.Div(id='shift-2-container', children=[create_shift_board_Shift_2(None, initial_state)])
        ]),

        html.Div(id='kanban-status-container', children=[create_kanban_status_boards(initial_state)]),
        html.Div(id='priority-table-container', children=[create_priority_ranking_table(initial_state)])

    ])


def layout_loop_a():
    """Overflow-Board Layout fürLoop A (SF2)"""
    try:
        products_a = load_sf2_buffers_from_material_zones()
        board_a = OverflowBoard(products=products_a)
        initial_state = board_a.to_dict()
    except:
        initial_state = {}

    return html.Div([
        dcc.Store(id='overflow-board-state-a', data=initial_state),
        dcc.Store(id='overflow-schedule-a', data={}),

        html.H3('Loop A (SF2) - Overflow-Board / Heijunka-Planung', style={'marginBottom': '1rem', 'color': '#2c3e50'}),
        html.Div([
            html.H4('Replenishment Orders', style={'marginBottom': '0.75rem', 'color': '#1a1a2e', 'fontSize': '1rem'}),
            html.Div(id='replenishment-cards-a')
        ], style={'marginBottom': '1.5rem'}),

        html.Div([
            html.Button('Planen (Loop A)', id='btn-produce-a', style={'padding': '0.5rem 1rem', 'backgroundColor': '#51CF66', 'color': 'white', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer'})
        ], style={'marginBottom': '1.5rem'}),

        html.Div(id='replenishment-cards-container-a', children=[
            create_replenishment_cards([], title='Replenishment Orders (Loop A)')
        ], style={'marginBottom': '1rem'}),

        html.Div(id='overflow-board-container-a', children=[
            create_board_grid(initial_state)
        ], style={'marginBottom': '2rem'}),

        html.Div([
            html.H4('Shift Plan 06:00 - 14:00', style={'marginBottom': '1rem', 'color': '#2c3e50', 'fontSize': '1rem'}),
            html.Div(id='shift-1-container-a', children=[create_shift_board_loop_a_shift_1(None, initial_state)])
        ]),

        html.Div([
            html.H4('Shift Plan 14:00 - 22:00', style={'marginBottom': '1rem', 'color': '#2c3e50', 'fontSize': '1rem'}),
            html.Div(id='shift-2-container-a', children=[create_shift_board_loop_a_shift_2(None, initial_state)])
        ]),

        html.Div(id='kanban-status-container-a', children=[create_kanban_status_boards(initial_state)]),
        html.Div(id='priority-table-container-a', children=[create_priority_ranking_table(initial_state)])

    ])


def layout():
    """Default Heijunka layout (Loop B)."""
    return layout_loop_b()
