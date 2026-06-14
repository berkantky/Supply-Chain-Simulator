"""
components/layout_dashboard.py

Hauptdashboard mit wichtigsten Kennzahlen:
- Bestellungen pro Produkt
- Materialverbrauch basierend auf BOM
"""

import pandas as pd
from dash import html, dcc, callback, Input, Output, State, no_update
import plotly.graph_objects as go
from utils.overflow_simulator import (
    get_daily_material_consumption,
    load_or_create_simulation_state,
    load_material_buffer_zones
)

# ============================================================================
# Chart Functions
# ============================================================================

def create_orders_chart(daily_orders: dict = None):
    """Zeige Bestellungen pro Produkt"""
    
    if not daily_orders or not isinstance(daily_orders, dict):
        daily_orders = {}
    
    if not daily_orders:
        return go.Figure().add_annotation(text="Keine Bestellungen heute")
    
    products = list(daily_orders.keys())
    quantities = list(daily_orders.values())
    
    colors = ['#51CF66' if q > 0 else '#999' for q in quantities]
    
    fig = go.Figure(data=[
        go.Bar(
            x=products,
            y=quantities,
            marker_color=colors,
            text=[f'{int(q)}' for q in quantities],
            textposition='auto',
            hovertemplate='%{x}<br>Bestellungen: %{y}<extra></extra>'
        )
    ])
    
    fig.update_layout(
        title='📦 Bestellungen heute',
        xaxis_title='Produkt',
        yaxis_title='Anzahl Bestellungen',
        height=300,
        autosize=False,
        margin=dict(b=50, l=50, r=20, t=50),
        showlegend=False,
        hovermode='x'
    )
    
    return fig


def _filter_raw_sf_consumption(consumption: dict) -> dict:
    if not consumption:
        return {}
    material_zones = load_material_buffer_zones()
    fg_set = {'CT5', 'CT6', 'CT7', 'TT6', 'TT7', 'TT8'}
    allowed = {name for name in material_zones.keys() if name not in fg_set}
    return {material: qty for material, qty in consumption.items() if material in allowed}


def _get_latest_booked_consumption():
    state = load_or_create_simulation_state()
    booked = getattr(state, 'booked_material_consumption', None)
    daily = getattr(booked, 'daily_consumption', {}) if booked else {}
    if not daily:
        return {}
    latest_day = max(int(day) for day in daily.keys())
    return daily.get(latest_day, {})


def create_material_consumption_chart(daily_orders: dict = None):
    """Zeige voraussichtlichen Materialverbrauch basierend auf Bestellungen (Rohstoffe + SF)."""
    if not daily_orders or not isinstance(daily_orders, dict):
        daily_orders = {}
    try:
        expected = get_daily_material_consumption(daily_orders)
    except Exception:
        return go.Figure().add_annotation(text="Fehler beim Berechnen des Materialverbrauchs")
    consumption = _filter_raw_sf_consumption(expected)
    if not consumption:
        return go.Figure().add_annotation(text="Kein voraussichtlicher Materialverbrauch")
    
    materials = list(consumption.keys())
    quantities = list(consumption.values())
    
    fig = go.Figure(data=[
        go.Bar(
            x=materials,
            y=quantities,
            marker_color='#5A9FBF',
            text=[f'{int(q)}' for q in quantities],
            textposition='auto',
            hovertemplate='%{x}<br>Verbrauch: %{y} pcs<extra></extra>'
        )
    ])
    
    fig.update_layout(
        title='🔧 Materialverbrauch(Voraussichtlich)',
        xaxis_title='Material',
        yaxis_title='Verbrauchte Menge [pcs]',
        height=300,
        autosize=False,
        margin=dict(b=100, l=50, r=20, t=50),
        xaxis_tickangle=-45,
        showlegend=False,
        hovermode='x'
    )
    
    return fig


def load_material_consumption_history_df() -> pd.DataFrame:
    """Lade gebuchten Materialverbrauchsverlauf (Rohstoffe + SF) aus dem Simulationszustand."""
    try:
        state = load_or_create_simulation_state()
        history = getattr(state, 'booked_material_consumption', None)
        daily = getattr(history, 'daily_consumption', {}) if history else {}
    except Exception:
        daily = {}
    
    if not daily:
        return pd.DataFrame(columns=['Day', 'Material', 'ConsumedQty'])
    
    records = []
    material_zones = load_material_buffer_zones()
    fg_set = {'CT5', 'CT6', 'CT7', 'TT6', 'TT7', 'TT8'}
    allowed = {name for name in material_zones.keys() if name not in fg_set}
    for day, consumption in sorted(daily.items()):
        for material, qty in consumption.items():
            if material not in allowed:
                continue
            records.append({'Day': int(day), 'Material': material, 'ConsumedQty': qty})
    
    return pd.DataFrame(records)


def create_material_history_chart(history_df: pd.DataFrame, selected_material: str = None):
    """Line-Chart für den Verbrauch eines ausgewaehlten Materials ueber die Tage."""
    fig = go.Figure()
    
    if history_df.empty:
        fig.add_annotation(
            text="Noch kein Materialverbrauch vorhanden",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False
        )
        fig.update_layout(height=320, margin=dict(t=40, l=40, r=20, b=40))
        return fig
    
    materials = history_df['Material'].unique().tolist()
    if not selected_material or selected_material not in materials:
        selected_material = materials[0]
    
    material_df = history_df[history_df['Material'] == selected_material].copy()
    if not material_df.empty:
        material_df['Day'] = material_df['Day'].astype(int)
        material_df = material_df.sort_values('Day')
    if material_df.empty:
        fig.add_annotation(
            text="Keine Daten für Auswahl",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False
        )
        fig.update_layout(height=320, margin=dict(t=40, l=40, r=20, b=40))
        return fig
    
    fig.add_trace(go.Scatter(
        x=material_df['Day'],
        y=material_df['ConsumedQty'],
        mode='lines+markers',
        name=selected_material,
        line=dict(color='#5A9FBF', width=3),
        marker=dict(size=8, color='#1E4258', line=dict(width=1, color='#fff')),
        hovertemplate='Produktion Tag %{x}<br>Verbrauch: %{y} pcs<extra></extra>'
    ))
    
    fig.update_layout(
        title=f'Verbrauchsverlauf: {selected_material}',
        xaxis_title='Produktion Tag',
        yaxis_title='Verbrauch [pcs]',
        height=360,
        margin=dict(b=60, l=60, r=30, t=60),
        hovermode='x unified',
        plot_bgcolor='rgba(240,244,248,0.6)',
        paper_bgcolor='white',
        xaxis=dict(
            gridcolor='rgba(0,0,0,0.08)',
            tickmode='linear',
            dtick=1,
            tickformat='.0f'
        ),
        yaxis=dict(gridcolor='rgba(0,0,0,0.08)')
    )
    
    return fig


def create_orders_summary_table(daily_orders: dict = None):
    """Zeige Bestellungs-Zusammenfassung als Tabelle"""
    
    if not daily_orders or not isinstance(daily_orders, dict):
        daily_orders = {}
    
    if not daily_orders:
        return html.Div("Keine Bestellungen", style={'padding': '1rem', 'color': '#999'})
    
    rows = []
    total = 0
    
    for product, qty in sorted(daily_orders.items()):
        total += qty
        rows.append(html.Tr([
            html.Td(product, style={'padding': '0.7rem', 'fontWeight': 'bold'}),
            html.Td(f'{int(qty)}', style={'padding': '0.7rem', 'textAlign': 'center', 'fontSize': '1.1rem', 'fontWeight': 'bold', 'color': '#51CF66'})
        ], style={'borderBottom': '1px solid #e0e0e0', 'backgroundColor': '#f8f9fa'}))
    
    rows.append(html.Tr([
        html.Td('GESAMT', style={'padding': '0.7rem', 'fontWeight': 'bold', 'backgroundColor': '#5A9FBF', 'color': 'white'}),
        html.Td(f'{int(total)}', style={'padding': '0.7rem', 'textAlign': 'center', 'fontSize': '1.1rem', 'fontWeight': 'bold', 'color': '#51CF66', 'backgroundColor': '#f0f0f0'})
    ], style={'fontWeight': 'bold'}))
    
    header = html.Tr([
        html.Th('Produkt', style={'padding': '0.7rem', 'textAlign': 'left', 'backgroundColor': '#5A9FBF', 'color': 'white'}),
        html.Th('Bestellungen', style={'padding': '0.7rem', 'textAlign': 'center', 'backgroundColor': '#5A9FBF', 'color': 'white'})
    ])
    
    return html.Table([header] + rows, style={
        'width': '100%',
        'borderCollapse': 'collapse',
        'borderRadius': '6px',
        'overflow': 'hidden',
        'boxShadow': '0 2px 6px rgba(0,0,0,0.08)'
    })


def create_material_consumption_table(booked_consumption: dict = None):
    """Zeige gebuchten Materialverbrauch (kumuliert)"""
    if not booked_consumption or not isinstance(booked_consumption, dict):
        booked_consumption = {}
    consumption = _filter_raw_sf_consumption(booked_consumption)
    if not consumption:
        return html.Div("Kein gebuchter Materialverbrauch", style={'padding': '1rem', 'color': '#999'})
    
    rows = []
    total = 0
    
    for material, qty in sorted(consumption.items()):
        total += qty
        rows.append(html.Tr([
            html.Td(material, style={'padding': '0.7rem', 'fontWeight': 'bold'}),
            html.Td(f'{int(qty)}', style={'padding': '0.7rem', 'textAlign': 'center', 'fontSize': '1.1rem', 'fontWeight': 'bold', 'color': '#5A9FBF'})
        ], style={'borderBottom': '1px solid #e0e0e0', 'backgroundColor': '#f8f9fa'}))
    
    rows.append(html.Tr([
        html.Td('GESAMT', style={'padding': '0.7rem', 'fontWeight': 'bold', 'backgroundColor': '#5A9FBF', 'color': 'white'}),
        html.Td(f'{int(total)}', style={'padding': '0.7rem', 'textAlign': 'center', 'fontSize': '1.1rem', 'fontWeight': 'bold', 'color': '#5A9FBF', 'backgroundColor': '#f0f0f0'})
    ], style={'fontWeight': 'bold'}))
    
    header = html.Tr([
        html.Th('Material', style={'padding': '0.7rem', 'textAlign': 'left', 'backgroundColor': '#5A9FBF', 'color': 'white'}),
        html.Th('Verbrauch [pcs]', style={'padding': '0.7rem', 'textAlign': 'center', 'backgroundColor': '#5A9FBF', 'color': 'white'})
    ])
    
    return html.Table([header] + rows, style={
        'width': '100%',
        'borderCollapse': 'collapse',
        'borderRadius': '6px',
        'overflow': 'hidden',
        'boxShadow': '0 2px 6px rgba(0,0,0,0.08)'
    })


# ============================================================================
# Main Layout
# ============================================================================

def layout():
    """Hauptdashboard mit KPIs"""
    
    # Gemeinsame Card-Styles für Hover-Effekte
    card_style = {
        'backgroundColor': 'white',
        'padding': '1.5rem',
        'borderRadius': '16px',
        'boxShadow': '0 4px 12px rgba(0,0,0,0.08)',
        'border': '1px solid #e8eef3',
        'transition': 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)'
    }
    
    return html.Div([
        # Header mit Icon
        html.Div([
            html.H2(
                '📊 Supply Chain Übersicht',
                style={
                    'marginBottom': '0.5rem', 
                    'color': '#1a1a2e',
                    'fontWeight': '700',
                    'fontSize': '1.75rem'
                }
            ),
            html.Div(
                "Schneller Überblick über heutige Bestellungen und gebuchte Verbräuche (Rohstoffe + SF).",
                style={'color': '#6a6a7a', 'fontSize': '0.95rem'}
            ),
        ], style={'marginBottom': '2rem'}),
        
        html.Div([
            html.Div([
                dcc.Graph(
                    id='dashboard-orders-chart',
                    figure=create_orders_chart(),
                    config={'responsive': False, 'displayModeBar': False},
                    style={'height': '300px'}
                )
            ], className='dashboard-card', style={
                'flex': '1', 
                'backgroundColor': 'white',
                'padding': '1rem',
                'borderRadius': '16px',
                'boxShadow': '0 4px 12px rgba(0,0,0,0.08)',
                'border': '1px solid #e8eef3',
                'transition': 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
            'minHeight': '360px'
            }),
            
            html.Div([
                dcc.Graph(
                    id='dashboard-consumption-chart',
                    figure=create_material_consumption_chart(),
                    config={'responsive': False, 'displayModeBar': False},
                    style={'height': '300px'}
                )
            ], className='dashboard-card', style={
                'flex': '1',
                'backgroundColor': 'white',
                'padding': '1rem',
                'borderRadius': '16px',
                'boxShadow': '0 4px 12px rgba(0,0,0,0.08)',
                'border': '1px solid #e8eef3',
                'transition': 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                'minHeight': '360px'
            })
        ], style={
            'display': 'flex',
            'marginBottom': '2rem',
            'gap': '1.5rem',
            'alignItems': 'stretch'
        }),
        
        # Verlauf Materialverbrauch
        html.Div([
            html.Div([
                html.Div([
                    html.H3('📈 Verbrauchsverlauf nach Material', style={
                         'marginBottom': '1rem', 
                         'color': '#1a1a2e', 
                         'fontSize': '1.1rem',
                         'fontWeight': '600',
                         'borderBottom': '2px solid #E8F4F8',
                         'paddingBottom': '0.75rem'
                    }),
                    html.Div(
                        "Wähle ein Material, um den Verbrauch ueber die simulierten Tage zu sehen.",
                        style={
                            'color': '#6a6a7a',
                            'fontSize': '0.9rem',
                            'marginBottom': '0.75rem'
                        }
                    )
                ]),
                dcc.Dropdown(
                    id='dashboard-material-dropdown',
                    options=[],
                    placeholder='Material auswählen',
                    style={'marginBottom': '1rem'}
                ),
                dcc.Graph(
                    id='dashboard-material-history-chart',
                    figure=create_material_history_chart(pd.DataFrame()),
                    config={'responsive': False, 'displayModeBar': False},
                    style={'height': '360px'}
                )
            ], className='dashboard-card', style={
                'flex': '1',
                'backgroundColor': 'white',
                'padding': '1.5rem',
                'borderRadius': '16px',
                'boxShadow': '0 4px 12px rgba(0,0,0,0.08)',
                'border': '1px solid #e8eef3',
                'transition': 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)'
            })
        ], style={
            'display': 'flex',
            'marginBottom': '2rem',
            'gap': '1.5rem'
        }),
        
        # Tabellen nebeneinander
        html.Div([
            html.Div([
                html.H3('📦 Bestellungs-Zusammenfassung', style={
                    'marginBottom': '1rem', 
                    'color': '#1a1a2e', 
                    'fontSize': '1.1rem',
                    'fontWeight': '600',
                    'borderBottom': '2px solid #E8F4F8',
                    'paddingBottom': '0.75rem'
                }),
                html.Div(
                    id='dashboard-orders-table',
                    children=[create_orders_summary_table()]
                )
            ], className='dashboard-card', style={
                'flex': '1',
                'backgroundColor': 'white',
                'padding': '1.5rem',
                'borderRadius': '16px',
                'boxShadow': '0 4px 12px rgba(0,0,0,0.08)',
                'border': '1px solid #e8eef3',
                'transition': 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
            'minHeight': '360px'
            }),
            
            html.Div([
                html.H3('🔧 Materialverbrauch-Zusammenfassung', style={
                    'marginBottom': '1rem', 
                    'color': '#1a1a2e', 
                    'fontSize': '1.1rem',
                    'fontWeight': '600',
                    'borderBottom': '2px solid #E8F4F8',
                    'paddingBottom': '0.75rem'
                }),
                html.Div(
                    id='dashboard-consumption-table',
                    children=[create_material_consumption_table()]
                )
            ], className='dashboard-card', style={
                'flex': '1',
                'backgroundColor': 'white',
                'padding': '1.5rem',
                'borderRadius': '16px',
                'boxShadow': '0 4px 12px rgba(0,0,0,0.08)',
                'border': '1px solid #e8eef3',
                'transition': 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)'
            })
        ], style={
            'display': 'flex',
            'gap': '1.5rem'
        })
    ], style={
        'padding': '2rem',
        'background': 'linear-gradient(135deg, #f0f4f8 0%, #e4ecf4 100%)',
        'minHeight': '100vh'
    })


# ============================================================================
# Callbacks - Update bei globaler Simulation
# ============================================================================

@callback(
    Output('dashboard-material-dropdown', 'options'),
    Output('dashboard-material-dropdown', 'value'),
    Input('global-simulation-state', 'data'),
    State('dashboard-material-dropdown', 'value'),
    prevent_initial_call=False
)
def update_material_dropdown(global_state_data, current_value):
    """Aktualisiere Materialliste fürden Verlaufs-Chart."""
    history_df = load_material_consumption_history_df()
    
    if history_df.empty:
        return [], None
    
    materials = sorted(history_df['Material'].unique().tolist())
    options = [{'label': m, 'value': m} for m in materials]
    
    if current_value in materials:
        return options, no_update
    
    return options, materials[0]


@callback(
    Output('dashboard-material-history-chart', 'figure'),
    Input('dashboard-material-dropdown', 'value'),
    Input('global-simulation-state', 'data'),
    prevent_initial_call=False
)
def update_material_history_chart(selected_material, global_state_data):
    """Zeige Verbrauchsverlauf fürdas ausgewaehlte Material."""
    history_df = load_material_consumption_history_df()
    return create_material_history_chart(history_df, selected_material)


@callback(
    [Output('dashboard-orders-chart', 'figure'),
     Output('dashboard-consumption-chart', 'figure'),
     Output('dashboard-orders-table', 'children'),
     Output('dashboard-consumption-table', 'children')],
    Input('global-simulation-state', 'data'),
    prevent_initial_call=False
)
def update_dashboard(global_state_data):
    """Aktualisiere Dashboard wenn Simulation sich aendert"""
    
    daily_orders = {}
    
    if global_state_data and isinstance(global_state_data, dict):
        daily_orders = global_state_data.get('daily_orders', {})
    booked_state = load_or_create_simulation_state()
    booked_total = {}
    booked_consumption_state = getattr(booked_state, 'booked_material_consumption', None)
    if booked_consumption_state:
        booked_total = getattr(booked_consumption_state, 'cumulative_consumption', {}) or {}

    return (
        create_orders_chart(daily_orders),
        create_material_consumption_chart(daily_orders),
        create_orders_summary_table(daily_orders),
        create_material_consumption_table(booked_total)
    )
