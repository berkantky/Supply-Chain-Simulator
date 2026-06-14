"""
components/layout_ddmrp_simulation.py

DDMRP Buffer Profile Simulation mit täglicher Prognoseschritt.
Zeigt Lager-Status und Net Flow basierend auf simulierten Bestellungen.
"""

import pandas as pd
import numpy as np
from dash import html, dcc, callback, Input, Output, State
import plotly.graph_objects as go
from pathlib import Path

from utils.overflow_simulator import (
    load_or_create_simulation_state, simulate_next_day, 
    save_simulation_to_csv, reset_simulation, load_buffer_zones_from_csv
)

# ============================================================================
# Data Loading
# ============================================================================

def load_buffer_profile_data():
    """Lade Buffer-Profile aus CSV"""
    csv_path = Path(__file__).parent.parent / 'data' / 'raw' / 'pufferzonen.csv'
    
    df = pd.read_csv(csv_path, index_col=0)
    
    # Extrahiere wichtige Zeilen
    try:
        komponenten = df.loc['Item', :].iloc[1:].tolist()  # Skip erste 2 Spalten
        green_zones = df.loc['Green Zone [pcs]', :].iloc[1:].tolist()
        yellow_zones = df.loc['Yellow Zone [pcs]', :].iloc[1:].tolist()
        red_zones = df.loc['Total Red Zone [pcs]', :].iloc[1:].tolist()
        
        # Bereinige None/NaN
        data = []
        for i, (name, g, y, r) in enumerate(zip(komponenten, green_zones, yellow_zones, red_zones)):
            if pd.notna(name) and str(name).strip():
                try:
                    data.append({
                        'name': str(name).strip(),
                        'green': float(g) if pd.notna(g) else 0,
                        'yellow': float(y) if pd.notna(y) else 0,
                        'red': float(r) if pd.notna(r) else 0,
                        'total': float(g) + float(y) + float(r) if pd.notna(g) and pd.notna(y) and pd.notna(r) else 0
                    })
                except:
                    pass
        
        return data
    except Exception as e:
        print(f"Fehler beim Laden der Buffer-Profile: {e}")
        return []


# ============================================================================
# Chart Creation Functions
# ============================================================================

def create_buffer_profile_chart(product_data: dict = None):
    """Erstelle gestapeltes Balkendiagramm für Buffer-Profile"""
    
    data = load_buffer_profile_data()
    
    if not data:
        return go.Figure().add_annotation(text="Keine Daten verfügbar")
    
    names = [d['name'] for d in data]
    green_vals = [d['green'] for d in data]
    yellow_vals = [d['yellow'] for d in data]
    red_vals = [d['red'] for d in data]
    
    fig = go.Figure(data=[
        go.Bar(name='Grüne Zone (Cycle Stock)', x=names, y=green_vals, 
               marker_color='#51CF66', hovertemplate='%{x}<br>Grün: %{y}<extra></extra>'),
        go.Bar(name='Gelbe Zone (Cycle Stock)', x=names, y=yellow_vals, 
               marker_color='#FFD700', hovertemplate='%{x}<br>Gelb: %{y}<extra></extra>'),
        go.Bar(name='Rote Zone (Safety Stock)', x=names, y=red_vals, 
               marker_color='#FF6B6B', hovertemplate='%{x}<br>Rot: %{y}<extra></extra>')
    ])
    
    fig.update_layout(
        barmode='stack',
        title='Buffer Profiles: Grün–Gelb–Rot Zonen pro Komponente',
        xaxis_title='Komponenten',
        yaxis_title='Kanban-Anzahl [pcs]',
        hovermode='x unified',
        height=400,
        margin=dict(b=100, l=50, r=20, t=50),
        xaxis_tickangle=-45,
        font=dict(size=10),
        showlegend=True,
        legend=dict(yanchor='top', y=0.99, xanchor='right', x=0.99)
    )
    
    return fig


def create_board_status_chart(board_state: dict = None):
    """Erstelle Chart mit aktuellem Overflow-Board Status"""
    
    if not board_state:
        board_state = {}
    
    if not board_state:
        return go.Figure().add_annotation(text="Kein Board-Status verfügbar")
    
    products = list(board_state.keys())
    greens = [board_state[p]['green_current'] for p in products]
    yellows = [board_state[p]['yellow_current'] for p in products]
    reds = [board_state[p]['red_current'] for p in products]
    
    fig = go.Figure(data=[
        go.Bar(name='Grün', x=products, y=greens, 
               marker_color='#51CF66', hovertemplate='%{x}<br>Grün: %{y}<extra></extra>'),
        go.Bar(name='Gelb', x=products, y=yellows, 
               marker_color='#FFD700', hovertemplate='%{x}<br>Gelb: %{y}<extra></extra>'),
        go.Bar(name='Rot', x=products, y=reds, 
               marker_color='#FF6B6B', hovertemplate='%{x}<br>Rot: %{y}<extra></extra>')
    ])
    
    fig.update_layout(
        barmode='stack',
        title='Aktueller Overflow-Board Status (Kanban-Verteilung)',
        xaxis_title='Produkte',
        yaxis_title='Kanban-Anzahl',
        hovermode='x unified',
        height=350,
        margin=dict(b=80, l=50, r=20, t=50),
        xaxis_tickangle=-45,
        font=dict(size=10),
        showlegend=True,
        legend=dict(yanchor='top', y=0.99, xanchor='right', x=0.99)
    )
    
    return fig


# ============================================================================
# Main Layout
# ============================================================================

def layout():
    """DDMRP Simulation Layout mit täglichem Simulator"""
    
    # Lade aktuellen Simulationszustand
    try:
        state = load_or_create_simulation_state()
        board_state = state.board.to_dict() if state.board else {}
        current_day = state.current_day
    except:
        board_state = {}
        current_day = 1
    
    return html.Div([
        # Store für Simulationszustand
        dcc.Store(id='ddmrp-simulation-state', data={'day': current_day, 'board': board_state}),
        
        html.H2(
            '📊 DDMRP Buffer Profiles & Tages-Simulation',
            style={'marginBottom': '1rem', 'color': '#2c3e50'}
        ),
        
        html.Div(
            'Tägliche Simulation der Kanban-Verwaltung: Verbrauch → Produktion → nächster Tag. Jeder Klick auf "Nächster Tag" simuliert einen Produktionstag und aktualisiert den Bestand.',
            style={'marginBottom': '2rem', 'color': '#666', 'fontStyle': 'italic'}
        ),
        
        # Steuerungselemente - VEREINFACHT
        html.Div([
            html.Div([
                html.Div([
                    html.Span(f"Aktueller Tag: ", style={'fontWeight': 'bold', 'marginRight': '0.5rem'}),
                    html.Span(id='current-day-display', children=str(current_day), style={'fontSize': '1.2rem', 'color': '#5A9FBF', 'fontWeight': 'bold'})
                ], style={'marginBottom': '1rem', 'display': 'flex', 'alignItems': 'center'}),
                
                html.Label('Tagesweise Simulation:', style={'fontWeight': 'bold', 'marginBottom': '0.5rem', 'display': 'block'}),
                html.Div([
                    html.Button(
                        '▶️ Nächster Tag simulieren',
                        id='btn-next-day',
                        style={
                            'padding': '0.75rem 1.5rem',
                            'backgroundColor': '#5A9FBF',
                            'color': 'white',
                            'border': 'none',
                            'borderRadius': '4px',
                            'cursor': 'pointer',
                            'fontWeight': 'bold',
                            'marginRight': '1rem'
                        }
                    ),
                    html.Button(
                        '💾 Daten speichern (CSV)',
                        id='btn-export-csv',
                        style={
                            'padding': '0.75rem 1.5rem',
                            'backgroundColor': '#51CF66',
                            'color': 'white',
                            'border': 'none',
                            'borderRadius': '4px',
                            'cursor': 'pointer',
                            'fontWeight': 'bold',
                            'marginRight': '1rem'
                        }
                    ),
                    html.Button(
                        '🔄 Simulation zurücksetzen',
                        id='btn-reset-simulation',
                        style={
                            'padding': '0.75rem 1.5rem',
                            'backgroundColor': '#999',
                            'color': 'white',
                            'border': 'none',
                            'borderRadius': '4px',
                            'cursor': 'pointer',
                            'fontWeight': 'bold'
                        }
                    )
                ], style={'display': 'flex', 'alignItems': 'center'})
            ], style={'marginBottom': '1rem'})
        ], style={
            'backgroundColor': 'white',
            'padding': '1.5rem',
            'borderRadius': '8px',
            'boxShadow': '0 2px 4px rgba(0,0,0,0.1)',
            'marginBottom': '1.5rem'
        }),
        
        # Tages-Status: Heute's Bestellungen und Produktion
        html.Div(id='daily-summary-container', children=[
            html.Div([
                html.Div([
                    html.H4('📦 Heutige Bestellungen', style={'marginBottom': '0.5rem', 'color': '#2c3e50'}),
                    html.Div(id='today-orders-text', children="Keine Simulation gestartet")
                ], style={'flex': 1, 'marginRight': '1rem', 'backgroundColor': '#f8f9fa', 'padding': '1rem', 'borderRadius': '6px', 'borderLeft': '3px solid #5A9FBF'}),
                html.Div([
                    html.H4("⚙️ Heutige Produktion", style={'marginBottom': '0.5rem', 'color': '#2c3e50'}),
                    html.Div(id='today-production-text', children="Keine Simulation gestartet")
                ], style={'flex': 1, 'backgroundColor': '#f8f9fa', 'padding': '1rem', 'borderRadius': '6px', 'borderLeft': '3px solid #51CF66'})
            ], style={'display': 'flex', 'marginBottom': '1.5rem'})
        ]),
        
        # Buffer Profile Chart
        html.Div([
            dcc.Graph(id='buffer-profile-chart', figure=create_buffer_profile_chart())
        ], style={
            'backgroundColor': 'white',
            'padding': '1.5rem',
            'borderRadius': '8px',
            'boxShadow': '0 2px 6px rgba(0,0,0,0.08)',
            'marginBottom': '1.5rem'
        }),
        
        # Board Status Chart
        html.Div([
            dcc.Graph(id='board-status-chart', figure=create_board_status_chart(board_state))
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
    [Output('ddmrp-simulation-state', 'data'),
     Output('current-day-display', 'children'),
     Output('board-status-chart', 'figure'),
     Output('today-orders-text', 'children'),
     Output('today-production-text', 'children')],
    [Input('btn-next-day', 'n_clicks'),
     Input('btn-reset-simulation', 'n_clicks'),
     Input('btn-export-csv', 'n_clicks')],
    prevent_initial_call=True
)
def update_simulation(n_next, n_reset, n_export):
    """Aktualisiere Simulationszustand basierend auf Button-Klicks"""
    from dash import callback_context
    
    ctx = callback_context
    if not ctx.triggered:
        raise Exception("Kein Trigger")
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # Lade aktuellen Zustand
    state = load_or_create_simulation_state()
    
    if trigger_id == 'btn-reset-simulation':
        # Setze zurück
        state = reset_simulation()
        today_orders_html = html.Div("Simulation zurückgesetzt", style={'color': '#999', 'fontStyle': 'italic'})
        today_production_html = html.Div("Simulation zurückgesetzt", style={'color': '#999', 'fontStyle': 'italic'})
    
    elif trigger_id == 'btn-next-day':
        # Simuliere nächsten Tag
        state, daily_orders, daily_production = simulate_next_day(state)
        
        # Formatiere Bestellungen
        if daily_orders:
            orders_text = html.Div([
                html.Div(f"{prod}: {qty} Stück", style={'fontSize': '0.9rem', 'marginBottom': '0.3rem'})
                for prod, qty in sorted(daily_orders.items())
            ])
        else:
            orders_text = html.Div("Keine Bestellungen", style={'color': '#999', 'fontStyle': 'italic'})
        
        today_orders_html = orders_text
        
        # Formatiere Produktion
        if daily_production:
            production_text = html.Div([
                html.Div(f"{prod}: {qty} Kanbans", style={'fontSize': '0.9rem', 'marginBottom': '0.3rem'})
                for prod, qty in sorted(daily_production.items())
            ])
        else:
            production_text = html.Div("Keine Produktion", style={'color': '#999', 'fontStyle': 'italic'})
        
        today_production_html = production_text
    
    elif trigger_id == 'btn-export-csv':
        # Exportiere zu CSV
        save_simulation_to_csv(state)
        today_orders_html = html.Div("✓ Daten in outputs/ gespeichert (daily_orders_log.csv, daily_production_log.csv, current_board_state.csv)", style={'color': '#51CF66', 'fontWeight': 'bold'})
        today_production_html = html.Div("")
    
    # Aktualisiere Charts
    board_state = state.board.to_dict() if state.board else {}
    board_chart = create_board_status_chart(board_state)
    
    state_data = {
        'day': state.current_day,
        'board': board_state
    }
    
    return state_data, str(state.current_day), board_chart, today_orders_html, today_production_html
