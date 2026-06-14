"""
components/layout_production.py

Production tab for executing daily production and reviewing results.
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, callback, Input, Output


def _build_table(title: str, planned: dict, executed: dict, shortages: dict):
    rows = []
    products = sorted(set((planned or {}).keys()) | set((executed or {}).keys()) | set((shortages or {}).keys()))
    for product in products:
        planned_qty = int((planned or {}).get(product, 0) or 0)
        executed_qty = int((executed or {}).get(product, 0) or 0)
        short_info = (shortages or {}).get(product, {})
        if short_info:
            missing_qty = int(short_info.get('missing', 0) or 0)
            limit = short_info.get('limit', '')
        elif executed:
            missing_qty = max(0, planned_qty - executed_qty)
            limit = ''
        else:
            missing_qty = 0
            limit = ''
        rows.append(html.Tr([
            html.Td(product, style={'padding': '0.5rem', 'fontSize': '0.85rem'}),
            html.Td(str(planned_qty), style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'}),
            html.Td(str(executed_qty), style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'}),
            html.Td(str(missing_qty), style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'}),
            html.Td(limit, style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'})
        ], style={'borderBottom': '1px solid #e0e0e0'}))

    if not rows:
        rows.append(html.Tr([
            html.Td("Keine Daten", colSpan=5, style={'padding': '0.7rem', 'color': '#888', 'textAlign': 'center'})
        ]))

    header = html.Tr([
        html.Th(title, colSpan=5, style={
            'padding': '0 0.5rem',
            'height': '44px',
            'lineHeight': '44px',
            'textAlign': 'left',
            'fontWeight': 'bold',
            'fontSize': '0.9rem',
            'backgroundColor': '#5A9FBF',
            'color': 'white',
            'whiteSpace': 'nowrap'
        })
    ])
    columns = html.Tr([
        html.Th('Produkt', style={'padding': '0 0.5rem', 'height': '36px', 'lineHeight': '36px', 'textAlign': 'left', 'fontSize': '0.8rem'}),
        html.Th('Geplant', style={'padding': '0 0.5rem', 'height': '36px', 'lineHeight': '36px', 'textAlign': 'center', 'fontSize': '0.8rem'}),
        html.Th('Produziert', style={'padding': '0 0.5rem', 'height': '36px', 'lineHeight': '36px', 'textAlign': 'center', 'fontSize': '0.8rem'}),
        html.Th('Fehlend', style={'padding': '0 0.5rem', 'height': '36px', 'lineHeight': '36px', 'textAlign': 'center', 'fontSize': '0.8rem'}),
        html.Th('Limit', style={'padding': '0 0.5rem', 'height': '36px', 'lineHeight': '36px', 'textAlign': 'center', 'fontSize': '0.8rem'})
    ], style={'backgroundColor': '#f0f4f7'})

    return html.Table([header, columns] + rows, style={
        'width': '100%',
        'borderCollapse': 'collapse',
        'borderRadius': '6px',
        'overflow': 'hidden',
        'boxShadow': '0 2px 6px rgba(0,0,0,0.08)',
        'backgroundColor': 'white',
        'minHeight': '360px'
    })



def _planned_from_schedule(schedule_slots: dict) -> dict:
    planned = {}
    for product, slots in (schedule_slots or {}).items():
        planned[product] = len(slots or [])
    return planned


def _planned_from_cards(cards: list) -> dict:
    planned = {}
    for item in cards or []:
        name = item.get('material')
        if not name:
            continue
        planned[name] = int(item.get('replenishment_qty', 0) or 0)
    return planned


def _planned_from_board_state(board_state: dict) -> dict:
    planned = {}
    for product, data in (board_state or {}).items():
        planned[product] = int((data or {}).get('current_total', 0) or 0)
    return planned


def _build_consumption_table(consumption: dict):
    rows = []
    for material in sorted((consumption or {}).keys()):
        qty = int(consumption.get(material, 0) or 0)
        rows.append(html.Tr([
            html.Td(material, style={'padding': '0.5rem', 'fontSize': '0.85rem'}),
            html.Td(str(qty), style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'})
        ], style={'borderBottom': '1px solid #e0e0e0'}))

    if not rows:
        rows.append(html.Tr([
            html.Td("Keine Buchungen", colSpan=2, style={'padding': '0.7rem', 'color': '#888', 'textAlign': 'center'})
        ]))

    header = html.Tr([
        html.Th('Materialverbrauch (Produktion)', colSpan=2, style={
            'padding': '0.6rem 0.5rem',
            'textAlign': 'left',
            'fontWeight': 'bold',
            'fontSize': '0.9rem',
            'backgroundColor': '#2F8F5B',
            'color': 'white'
        })
    ])
    columns = html.Tr([
        html.Th('Material', style={'padding': '0.4rem 0.5rem', 'textAlign': 'left', 'fontSize': '0.8rem'}),
        html.Th('Menge', style={'padding': '0.4rem 0.5rem', 'textAlign': 'center', 'fontSize': '0.8rem'})
    ], style={'backgroundColor': '#f0f4f7'})

    return html.Table([header, columns] + rows, style={
        'width': '100%',
        'borderCollapse': 'collapse',
        'borderRadius': '6px',
        'overflow': 'hidden',
        'boxShadow': '0 2px 6px rgba(0,0,0,0.08)',
        'backgroundColor': 'white'
    })


def _load_routing_production_times():
    csv_path = Path(__file__).parent.parent / 'data' / 'Routing_Produktionzeit.csv'
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    if df.empty:
        return None
    op_col = df.columns[0]
    df = df.rename(columns={op_col: 'Operation'})
    for col in df.columns:
        if col == 'Operation':
            continue
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(',', '.', regex=False)
            .str.replace('"', '', regex=False)
        )
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def _build_utilization_table(plan_b: dict, slots_per_day: int = 20, pitch_minutes: int = 42):
    df = _load_routing_production_times()
    if df is None or not plan_b:
        return html.Table([
            html.Tr([html.Th('Maschinenauslastung (Loop B)', colSpan=5, style={
                'padding': '0.6rem 0.5rem',
                'textAlign': 'left',
                'fontWeight': 'bold',
                'fontSize': '0.9rem',
                'backgroundColor': '#5A9FBF',
                'color': 'white'
            })]),
            html.Tr([html.Td("Keine Daten", colSpan=5, style={
                'padding': '0.7rem',
                'color': '#888',
                'textAlign': 'center'
            })])
        ], style={
            'width': '100%',
            'borderCollapse': 'collapse',
            'borderRadius': '6px',
            'overflow': 'hidden',
            'boxShadow': '0 2px 6px rgba(0,0,0,0.08)',
            'backgroundColor': 'white'
        })

    capacity_day = int(slots_per_day * pitch_minutes)
    capacity_shift = int(capacity_day / 2)

    rows = []
    for _, row in df.iterrows():
        operation = str(row.get('Operation', '')).strip()
        if not operation or operation.lower() == 'total':
            continue
        required = 0.0
        for product, qty in (plan_b or {}).items():
            if product not in df.columns:
                continue
            minutes_per_piece = row.get(product)
            if pd.isna(minutes_per_piece):
                continue
            required += float(qty) * float(minutes_per_piece)
        utilization = (required / capacity_day * 100) if capacity_day > 0 else 0.0
        rows.append(html.Tr([
            html.Td(operation, style={'padding': '0.5rem', 'fontSize': '0.85rem'}),
            html.Td(f"{required:.1f}", style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'}),
            html.Td(str(capacity_day), style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'}),
            html.Td(str(capacity_shift), style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem'}),
            html.Td(f"{utilization:.1f}%", style={'padding': '0.5rem', 'textAlign': 'center', 'fontSize': '0.85rem', 'fontWeight': 'bold'})
        ], style={'borderBottom': '1px solid #e0e0e0'}))

    if not rows:
        rows.append(html.Tr([
            html.Td("Keine Daten", colSpan=5, style={'padding': '0.7rem', 'color': '#888', 'textAlign': 'center'})
        ]))

    header = html.Tr([html.Th('Maschinenauslastung', colSpan=5, style={
        'padding': '0.6rem 0.5rem',
        'textAlign': 'left',
        'fontWeight': 'bold',
        'fontSize': '0.9rem',
        'backgroundColor': '#5A9FBF',
        'color': 'white'
    })])
    columns = html.Tr([
        html.Th('Operation', style={'padding': '0.4rem 0.5rem', 'textAlign': 'left', 'fontSize': '0.8rem'}),
        html.Th('Bedarf (min/Tag)', style={'padding': '0.4rem 0.5rem', 'textAlign': 'center', 'fontSize': '0.8rem'}),
        html.Th('Kapazitaet (min/Tag)', style={'padding': '0.4rem 0.5rem', 'textAlign': 'center', 'fontSize': '0.8rem'}),
        html.Th('Kapazitaet (min/Schicht)', style={'padding': '0.4rem 0.5rem', 'textAlign': 'center', 'fontSize': '0.8rem'}),
        html.Th('Utilization %', style={'padding': '0.4rem 0.5rem', 'textAlign': 'center', 'fontSize': '0.8rem'})
    ], style={'backgroundColor': '#f0f4f7'})

    return html.Table([header, columns] + rows, style={
        'width': '100%',
        'borderCollapse': 'collapse',
        'borderRadius': '6px',
        'overflow': 'hidden',
        'boxShadow': '0 2px 6px rgba(0,0,0,0.08)',
        'backgroundColor': 'white'
    })


def _build_utilization_figure(plan_b: dict, slots_per_day: int = 20, pitch_minutes: int = 42):
    df = _load_routing_production_times()
    if df is None or not plan_b:
        return go.Figure()

    capacity_day = float(slots_per_day * pitch_minutes)
    operations = []
    utilization = []

    for _, row in df.iterrows():
        operation = str(row.get('Operation', '')).strip()
        if not operation or operation.lower() == 'total':
            continue
        required = 0.0
        for product, qty in (plan_b or {}).items():
            if product not in df.columns:
                continue
            minutes_per_piece = row.get(product)
            if pd.isna(minutes_per_piece):
                continue
            required += float(qty) * float(minutes_per_piece)
        util_pct = (required / capacity_day * 100) if capacity_day > 0 else 0.0
        operations.append(operation)
        utilization.append(util_pct)

    fig = go.Figure(
        data=[
            go.Bar(
                x=operations,
                y=utilization,
                marker_color='#5A9FBF',
                text=[f"{v:.1f}%" for v in utilization],
                textposition='outside'
            )
        ]
    )
    fig.update_layout(
        title='Maschinenauslastung',
        yaxis_title='Utilization %',
        xaxis_title='Operation',
        yaxis=dict(range=[0, max(100, max(utilization or [0]) + 10)]),
        plot_bgcolor='white',
        paper_bgcolor='white',
        margin=dict(l=30, r=20, t=50, b=40)
    )
    return fig


def layout():
    return html.Div([
        html.Div([
            html.H2('Produktion', style={'marginBottom': '0.5rem', 'color': '#2c3e50'}),
            html.Div(
                'Produktion wird sofort gebucht (Output + BOM-Verbrauch). Versand/Demand bleibt am Next Day.',
                style={'color': '#666', 'marginBottom': '1rem'}
            ),
            html.Button(
                'Produzieren',
                id='btn-execute-production',
                style={
                    'padding': '0.7rem 1.4rem',
                    'background': 'linear-gradient(135deg, #51CF66 0%, #40C057 100%)',
                    'color': 'white',
                    'border': 'none',
                    'borderRadius': '8px',
                    'cursor': 'pointer',
                    'fontWeight': '600',
                    'fontSize': '0.9rem',
                    'boxShadow': '0 4px 12px rgba(81, 207, 102, 0.3)'
                }
            ),
            html.Div(id='production-status', style={'marginTop': '0.75rem'})
        ], style={
            'backgroundColor': 'white',
            'padding': '1.5rem',
            'borderRadius': '8px',
            'boxShadow': '0 2px 4px rgba(0,0,0,0.08)',
            'marginBottom': '1.5rem'
        }),
        html.Div([
            html.Div(id='production-loop-a-table', style={'minHeight': '360px'}),
            html.Div(id='production-loop-b-table', style={'minHeight': '360px'})
        ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(auto-fit, minmax(320px, 1fr))', 'gap': '1rem', 'alignItems': 'stretch'}),
        html.Div(id='production-material-table', style={'marginTop': '1.5rem'}),
        html.Div(id='production-utilization-table', style={'marginTop': '1.5rem'}),
        dcc.Graph(id='production-utilization-graph', style={'marginTop': '1.5rem'})
    ], style={'padding': '2rem'})


@callback(
    [Output('production-loop-a-table', 'children'),
     Output('production-loop-b-table', 'children'),
     Output('production-material-table', 'children'),
     Output('production-utilization-table', 'children'),
     Output('production-utilization-graph', 'figure'),
     Output('production-status', 'children')],
    [Input('global-simulation-state', 'data'),
     Input('overflow-schedule-b', 'data'),
     Input('overflow-schedule-a', 'data')]
)
def update_production_view(global_state, schedule_b, schedule_a):
    state = global_state or {}
    planned_b = _planned_from_cards(state.get('replenishment_cards', []) or [])
    planned_a = _planned_from_cards(state.get('replenishment_cards_a', []) or [])
    plan_b = state.get('daily_production', {}) or planned_b
    plan_a = state.get('daily_production_a', {}) or planned_a
    schedule_plan_b = _planned_from_schedule(schedule_b)
    schedule_plan_a = _planned_from_schedule(schedule_a)
    has_schedule_b = any(qty > 0 for qty in schedule_plan_b.values()) if schedule_plan_b else False
    has_schedule_a = any(qty > 0 for qty in schedule_plan_a.values()) if schedule_plan_a else False
    executed_b_day = state.get('production_executed', {}) or {}
    executed_a_day = state.get('production_executed_a', {}) or {}
    shortages_b_day = state.get('production_shortages', {}) or {}
    shortages_a_day = state.get('production_shortages_a', {}) or {}
    consumption = state.get('production_consumption', {}) or {}
    status = state.get('production_status', '')

    blocked_msg = "Bitte zuerst Heijunka planen (Loop A und Loop B), bevor Produzieren erlaubt ist."
    if status == blocked_msg:
        status = ""

    status_node = ""

    planned_for_a_day = schedule_plan_a if has_schedule_a else plan_a
    planned_for_b_day = schedule_plan_b if has_schedule_b else plan_b

    planned_snapshot_a = state.get('planned_snapshot_a')
    planned_snapshot_b = state.get('planned_snapshot')
    planned_for_a = planned_snapshot_a if isinstance(planned_snapshot_a, dict) else _planned_from_board_state(state.get('board_a', {}))
    planned_for_b = planned_snapshot_b if isinstance(planned_snapshot_b, dict) else _planned_from_board_state(state.get('board', {}))
    planned_for_a = planned_for_a or planned_for_a_day
    planned_for_b = planned_for_b or planned_for_b_day

    table_a = _build_table(
        'Loop A (Antriebswellen)',
        planned_for_a,
        executed_a_day,
        shortages_a_day
    )
    table_b = _build_table(
        'Loop B (Fertigwaren)',
        planned_for_b,
        executed_b_day,
        shortages_b_day
    )
    table_m = _build_consumption_table(consumption)
    table_u = _build_utilization_table(planned_for_b_day)
    fig_u = _build_utilization_figure(planned_for_b_day)

    return table_a, table_b, table_m, table_u, fig_u, status_node
